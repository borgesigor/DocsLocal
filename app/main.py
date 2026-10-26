from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import threading
import webbrowser
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import api
from app.core.config import CONFIG, PROJECTS, REPO, STATE
from app.core.exceptions import AppError, app_error_handler
from app.core.security import document_path
from app.services import document_service, project_service
from app.services.github_service import sync_manager
from app.services.instance_lock import InstanceLock
from app.services.onboarding_service import ensure_welcome_documentation
from app.services.storage import atomic_write
from app.services.update_service import update_manager
from app.version import VERSION

instance_lock = InstanceLock()


async def run_periodic_sync():
    while True:
        interval = max(10, int(CONFIG['git']['periodic_check_seconds']))
        if sync_manager.status.get('retry_count'):
            interval = max(interval, min(300, 10 * 2 ** min(sync_manager.status['retry_count'], 5)))
        await asyncio.sleep(interval)
        if (
            CONFIG['github']['enabled']
            and sync_manager.is_authenticated()
        ):
            # This scans local hashes only. A clean queue never contacts GitHub.
            await sync_manager.trigger(0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    instance_lock.acquire()
    periodic_task = None
    update_task = None
    try:
        REPO.mkdir(parents=True, exist_ok=True)
        PROJECTS.mkdir(parents=True, exist_ok=True)
        STATE.mkdir(parents=True, exist_ok=True)
        gitignore = REPO / '.gitignore'
        if not gitignore.exists():
            atomic_write(gitignore, '.DS_Store\nThumbs.db\n')

        ensure_welcome_documentation(STATE)
        sync_manager.resume()
        update_manager.prepare_shutdown = sync_manager.prepare_shutdown
        update_manager.resume = sync_manager.resume
        sync_manager.start()
        if CONFIG['github']['enabled'] and sync_manager.is_authenticated():
            await sync_manager.trigger(0)

        periodic_task = asyncio.create_task(run_periodic_sync())
        update_task = asyncio.create_task(update_manager.watch())
        yield
    finally:
        tasks = [task for task in (periodic_task, update_task, sync_manager.worker) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        instance_lock.release()


app = FastAPI(
    title='Docs Local API',
    version=VERSION,
    description='Documentação Markdown local-first com APIs REST.',
    lifespan=lifespan,
)
app.add_exception_handler(AppError, app_error_handler)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=['127.0.0.1', 'localhost', '::1', 'docs.local', 'testserver'],
)


@app.middleware('http')
async def origin_guard(request: Request, call_next):
    is_write_request = request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}
    origin = request.headers.get('origin')
    if is_write_request and origin:
        parsed_origin = normalized_origin(origin, origin_header=True)
        if (
            parsed_origin is None
            or parsed_origin != normalized_origin(str(request.url))
        ):
            return JSONResponse(
                status_code=403,
                content={
                    'error': {
                        'code': 'invalid_origin',
                        'message': 'Origem não permitida.',
                    }
                },
            )
    has_body = request.headers.get('content-length', '0') != '0' or 'transfer-encoding' in request.headers
    is_upload = (
        request.method == 'POST'
        and request.url.path.startswith('/api/v1/projects/')
        and request.url.path.endswith('/files')
        and len(request.url.path.split('/')) == 6
    )
    if is_write_request and has_body and not is_upload:
        media_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if media_type != 'application/json':
            return JSONResponse(status_code=415, content={
                'error': {'code': 'json_required', 'message': 'Envie o corpo como application/json.'}
            })
    return await call_next(request)


def normalized_origin(value: str, *, origin_header: bool = False):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        if origin_header and (parsed.path or parsed.query or parsed.fragment):
            return None
        default_port = 443 if parsed.scheme == 'https' else 80
        return parsed.scheme, parsed.hostname.lower(), parsed.port if parsed.port is not None else default_port
    except ValueError:
        return None


app.include_router(api)
STATIC_FILES = Path(__file__).parent / 'static'
BUILT_FILES = STATIC_FILES / 'dist'
app.mount('/static', StaticFiles(directory=STATIC_FILES), name='static')


@app.get('/')
def index():
    return FileResponse(BUILT_FILES / 'index.html')


def document_view(project_id: str, path: str):
    project_folder, _ = project_service.get_folder(project_id)
    document_path(project_folder, path)
    if not any(document['path'] == path for document in document_service.list_documents(project_id)):
        raise AppError(404, 'document_not_found', 'Documento não encontrado.')
    return index()


@app.get('/{project_id}/index.md', include_in_schema=False)
def project_index_view(project_id: str):
    return document_view(project_id, 'index.md')


@app.get('/{project_id}/docs/{path:path}', include_in_schema=False)
def project_document_view(project_id: str, path: str):
    return document_view(project_id, f'docs/{path}')


@app.get('/{project_id}', include_in_schema=False)
def project_view(project_id: str):
    project_service.get_folder(project_id)
    return index()


def open_browser_later():
    webbrowser.open(f"http://{CONFIG['server']['host']}:{CONFIG['server']['port']}")


if __name__ == '__main__':
    if CONFIG['server']['open_browser_on_start']:
        threading.Timer(1.0, open_browser_later).start()
    uvicorn.run(
        app,
        host=CONFIG['server']['host'],
        port=int(CONFIG['server']['port']),
        workers=1,
    )
