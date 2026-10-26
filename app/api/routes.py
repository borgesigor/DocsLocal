import asyncio
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Header, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.config import CONFIG, DATA, PROJECTS, REPO
from app.core.exceptions import AppError
from app.core.security import inside, project_folder_path, relative_doc_path
from app.services import document_service as documents
from app.services import project_service as projects
from app.services import search_service as search
from app.services.integrity_service import check_integrity
from app.services.github_client import GitHubAPIError
from app.services.github_service import sync_manager
from app.services.update_service import update_manager
from app.services.updater import UpdateError
from app.services.storage import atomic_write
from app.services.toml_writer import dumps as write_toml

api = APIRouter(prefix='/api/v1')
ALLOWED_CONFIG_OPTIONS = {
    'server': {'host', 'port', 'open_browser_on_start'},
    'storage': {'repository_path'},
    'git': {
        'enabled',
        'remote',
        'branch',
        'sync_debounce_seconds',
        'retry_enabled',
        'periodic_check_seconds',
    },
    'github': {'enabled', 'repository_name'},
    'editor': {'autosave_enabled', 'autosave_debounce_ms'},
    'search': {'enabled'},
    'logging': {'level'},
}
ALLOWED_UPLOAD_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.pdf', '.txt', '.csv', '.zip'
}
REMOTE_NAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]+$')
BRANCH_NAME_PATTERN = re.compile(r'^[A-Za-z0-9._/-]+$')
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    archived: bool | None = None


class DocumentCreate(BaseModel):
    path: str
    title: str = Field(default='Sem título', max_length=300)
    content: str | None = None


class DocumentPut(BaseModel):
    content: str
    revision: int | None = None


class DocumentPatch(BaseModel):
    path: str | None = None
    title: str | None = None


class FolderCreate(BaseModel):
    path: str


class FolderMove(BaseModel):
    path: str
    new_path: str


class GitHubDeviceAttempt(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9_-]+$')


class UpdateHold(BaseModel):
    client_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    dirty: bool


@api.get('/projects')
def list_projects(include_archived: bool = False):
    return projects.list_projects(include_archived=include_archived)


@api.post('/projects', status_code=201)
async def create_project(data: ProjectCreate):
    created_project = projects.create_project(data.name, data.description)
    await sync_manager.trigger()
    return created_project


@api.get('/projects/{project_id}')
def get_project(project_id: str):
    return projects.get_folder(project_id)[1]


@api.patch('/projects/{project_id}')
async def update_project(project_id: str, data: ProjectPatch):
    updated_project = projects.update_project(
        project_id,
        data.model_dump(exclude_unset=True),
    )
    await sync_manager.trigger()
    return updated_project


@api.delete('/projects/{project_id}')
async def archive_project(project_id: str, confirm: bool = False):
    if not confirm:
        raise AppError(
            400,
            'confirmation_required',
            'Envie confirm=true para arquivar este projeto.',
        )
    archived_project = projects.delete_project(project_id)
    await sync_manager.trigger()
    return archived_project


@api.get('/projects/{project_id}/tree')
def get_project_tree(project_id: str):
    return documents.tree(project_id)


@api.get('/projects/{project_id}/documents')
def list_documents(project_id: str):
    return documents.list_documents(project_id)


@api.post('/projects/{project_id}/documents', status_code=201)
async def create_document(project_id: str, data: DocumentCreate):
    created_document = documents.create_document(
        project_id,
        data.path,
        data.title,
        data.content,
    )
    await sync_manager.trigger()
    return created_document


@api.get('/projects/{project_id}/documents/{document_id}')
def get_document(project_id: str, document_id: str, response: Response):
    document = documents.read_document(project_id, document_id)
    response.headers['ETag'] = f'"{document["etag"]}"'
    return document


@api.put('/projects/{project_id}/documents/{document_id}')
async def update_document(
    project_id: str,
    document_id: str,
    data: DocumentPut,
    if_match: str | None = Header(default=None),
):
    expected_revision = data.revision
    if expected_revision is None and if_match is None:
        raise AppError(
            428,
            'revision_required',
            'Informe a revisão atual do documento ou envie o cabeçalho If-Match.',
        )
    if if_match:
        current_document = documents.read_document(project_id, document_id)
        etag_matches = if_match.strip('"') == current_document['etag']
        expected_revision = current_document['revision'] if etag_matches else -1

    saved_document = documents.update_document(
        project_id,
        document_id,
        data.content,
        expected_revision,
    )
    await sync_manager.trigger()
    return saved_document


@api.patch('/projects/{project_id}/documents/{document_id}')
async def patch_document(project_id: str, document_id: str, data: DocumentPatch):
    current_document = documents.read_document(project_id, document_id)
    content = current_document['content']

    if data.title is not None:
        lines = content.splitlines()
        heading_index = next(
            (index for index, line in enumerate(lines) if line.startswith('# ')),
            None,
        )
        if heading_index is None:
            lines.insert(0, f'# {data.title}')
        else:
            lines[heading_index] = f'# {data.title}'
        content = '\n'.join(lines) + ('\n' if current_document['content'].endswith('\n') else '')

    saved_document = documents.update_document(
        project_id,
        document_id,
        content,
        current_document['revision'],
        data.path,
    )
    await sync_manager.trigger()
    return saved_document


@api.delete('/projects/{project_id}/documents/{document_id}')
async def delete_document(project_id: str, document_id: str):
    result = documents.delete_document(project_id, document_id)
    await sync_manager.trigger()
    return result


@api.get('/projects/{project_id}/documents/{document_id}/history')
def document_history(project_id: str, document_id: str):
    document = documents.read_document(project_id, document_id)
    return sync_manager.document_history(project_id, document['path'])


@api.get('/projects/{project_id}/folders')
def list_folders(project_id: str):
    def find_folders(tree_nodes, parent_path=''):
        folder_paths = []
        for node in tree_nodes:
            if node['type'] != 'folder':
                continue
            path = f"{parent_path}/{node['name']}".strip('/')
            folder_paths.append({'path': path})
            folder_paths.extend(find_folders(node['children'], path))
        return folder_paths

    return find_folders(documents.tree(project_id))


@api.post('/projects/{project_id}/folders', status_code=201)
async def create_folder(project_id: str, request: Request):
    payload = FolderCreate.model_validate(await request.json())
    result = documents.create_folder(project_id, payload.path)
    await sync_manager.trigger()
    return result


@api.patch('/projects/{project_id}/folders')
async def move_folder(project_id: str, request: Request):
    payload = FolderMove.model_validate(await request.json())
    project_folder, _ = projects.get_folder(project_id)
    source = project_folder_path(project_folder, payload.path)
    destination = project_folder_path(project_folder, payload.new_path)

    if not source.is_dir():
        raise AppError(404, 'folder_not_found', 'Pasta não encontrada.')
    if destination.exists():
        raise AppError(409, 'path_exists', 'Já existe um arquivo ou pasta nesse caminho.')
    if source in destination.parents:
        raise AppError(400, 'invalid_path', 'Uma pasta não pode ser movida para dentro de si mesma.')

    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    projects.touch_project(project_id)
    await sync_manager.trigger()
    return {'path': destination.relative_to(project_folder).as_posix()}


@api.delete('/projects/{project_id}/folders')
async def delete_folder(project_id: str, path: str):
    project_folder, project = projects.get_folder(project_id)
    projects.ensure_deletable(project)
    folder_path = project_folder_path(project_folder, path)
    if not folder_path.is_dir():
        raise AppError(404, 'folder_not_found', 'Pasta não encontrada.')

    shutil.rmtree(folder_path)
    projects.touch_project(project_id)
    await sync_manager.trigger()
    return {'deleted': True, 'path': path}


@api.get('/projects/{project_id}/files')
def list_files(project_id: str):
    project_folder, _ = projects.get_folder(project_id)
    assets_folder = project_folder / 'assets'
    files = []
    for path in assets_folder.rglob('*'):
        if not path.is_file() or path.is_symlink() or path.name == '.gitkeep':
            continue
        inside(assets_folder, path)
        files.append(
            {
                'path': path.relative_to(assets_folder).as_posix(),
                'size': path.stat().st_size,
            }
        )
    return files


@api.post('/projects/{project_id}/files', status_code=201)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    path: str | None = None,
):
    project_folder, _ = projects.get_folder(project_id)
    filename = Path(path or file.filename or 'upload').name
    if filename in {'', '.', '..'} or len(filename) > 180:
        raise AppError(422, 'invalid_filename', 'Nome de arquivo inválido.')

    extension = Path(filename).suffix.casefold()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise AppError(415, 'file_type_not_allowed', 'Tipo de arquivo não permitido.')

    destination = inside(project_folder, project_folder / 'assets' / filename)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise AppError(413, 'file_too_large', 'O tamanho máximo do anexo é 20 MB.')
    if destination.exists():
        raise AppError(409, 'file_exists', 'Já existe um anexo com esse nome.')

    atomic_write(destination, content)
    projects.touch_project(project_id)
    await sync_manager.trigger()
    return {'path': filename, 'size': len(content)}


@api.get('/projects/{project_id}/files/{filename:path}')
def download_file(project_id: str, filename: str):
    project_folder, _ = projects.get_folder(project_id)
    file_path = inside(
        project_folder / 'assets',
        project_folder / 'assets' / relative_doc_path(filename),
    )
    if not file_path.is_file():
        raise AppError(404, 'file_not_found', 'Anexo não encontrado.')
    return FileResponse(file_path, filename=file_path.name)


@api.delete('/projects/{project_id}/files/{filename:path}')
async def delete_file(project_id: str, filename: str):
    project_folder, project = projects.get_folder(project_id)
    projects.ensure_deletable(project)
    file_path = inside(
        project_folder / 'assets',
        project_folder / 'assets' / relative_doc_path(filename),
    )
    if not file_path.is_file():
        raise AppError(404, 'file_not_found', 'Anexo não encontrado.')

    file_path.unlink()
    projects.touch_project(project_id)
    await sync_manager.trigger()
    return {'deleted': True}


@api.get('/search')
def search_documents(q: str, project_id: str | None = None):
    if not CONFIG['search']['enabled']:
        raise AppError(503, 'search_disabled', 'Pesquisa desativada.')
    return search.search(q, project_id)


@api.get('/github/auth/status')
async def github_auth_status():
    return await sync_manager.authentication_status()


@api.post('/github/auth/start')
async def start_github_authorization():
    try:
        return await asyncio.to_thread(sync_manager.start_device_authorization)
    except GitHubAPIError:
        raise AppError(502, 'github_login_unavailable', 'Não foi possível conectar ao GitHub. Tente novamente.')


@api.post('/github/auth/poll')
async def poll_github_authorization(data: GitHubDeviceAttempt):
    try:
        result = await asyncio.to_thread(sync_manager.poll_device_authorization, data.attempt_id)
    except GitHubAPIError:
        raise AppError(502, 'github_login_unavailable', 'Não foi possível conectar ao GitHub. Tente novamente.')
    if result['status'] == 'authenticated' and sync_manager.status['state'] == 'idle':
        await sync_manager.trigger(0)
    return result


@api.post('/github/auth/cancel')
def cancel_github_authorization(data: GitHubDeviceAttempt):
    sync_manager.cancel_device_authorization(data.attempt_id)
    return {'status': 'cancelled'}


@api.delete('/github/auth')
def logout_github():
    sync_manager.logout()
    return {'authenticated': False}


@api.get('/sync/status')
async def sync_status():
    return await sync_manager.status_details()


@api.get('/updates/status')
def update_status():
    return update_manager.status()


@api.post('/updates/check')
async def check_updates():
    return await asyncio.to_thread(update_manager.check, manual=True)


@api.post('/updates/defer')
def defer_update():
    return update_manager.defer()


@api.post('/updates/hold')
def hold_update(data: UpdateHold):
    update_manager.hold(data.client_id, data.dirty)
    return {'held': data.dirty}


@api.post('/updates/install', status_code=202)
def install_update():
    try:
        return update_manager.start_install()
    except UpdateError as error:
        raise AppError(409, 'update_unavailable', str(error))


@api.post('/sync/trigger', status_code=202)
async def request_sync():
    return await sync_manager.trigger(0)


@api.get('/sync/history')
def sync_history():
    return sync_manager.history()


@api.get('/sync/errors')
def sync_errors():
    error = sync_manager.status.get('last_error')
    if not error:
        return []
    return [{'error': error, 'state': sync_manager.status.get('state')}]


@api.get('/health')
def health():
    return {'status': 'ok', 'service': 'docs-local'}


@api.get('/system/config')
def get_system_config():
    return {
        section: {
            key: value
            for key, value in options.items()
            if key not in {'token', 'password'}
        }
        for section, options in CONFIG.items()
    }


@api.patch('/system/config')
async def update_system_config(request: Request):
    incoming = await request.json()
    if not isinstance(incoming, dict):
        raise AppError(422, 'invalid_config', 'A configuração deve ser um objeto JSON.')

    proposed = {section: dict(options) for section, options in CONFIG.items()}
    for section, values in incoming.items():
        if section not in ALLOWED_CONFIG_OPTIONS or not isinstance(values, dict):
            raise AppError(422, 'invalid_config', 'Seções de configuração inválidas.')
        for key, value in values.items():
            if key not in ALLOWED_CONFIG_OPTIONS[section]:
                raise AppError(422, 'invalid_config', f'Opção desconhecida: {section}.{key}')
            proposed[section][key] = value

    validate_config(proposed)
    atomic_write(DATA / 'config.toml', write_toml(proposed))
    CONFIG.clear()
    CONFIG.update(proposed)
    await sync_manager.trigger(0)
    return get_system_config()


def validate_config(config):
    server_host = config['server']['host']
    if not isinstance(server_host, str) or server_host not in {'127.0.0.1', 'localhost', '::1'}:
        raise AppError(422, 'unsafe_host', 'O servidor deve permanecer em loopback.')
    try:
        port = int(config['server']['port'])
        debounce = int(config['git']['sync_debounce_seconds'])
        check_interval = int(config['git']['periodic_check_seconds'])
        autosave_delay = int(config['editor']['autosave_debounce_ms'])
    except (TypeError, ValueError):
        raise AppError(422, 'invalid_config', 'Porta e intervalos Git precisam ser números inteiros.')
    if not 1 <= port <= 65535:
        raise AppError(422, 'invalid_port', 'Porta inválida.')
    if not 0 <= debounce <= 300:
        raise AppError(422, 'invalid_config', 'Debounce Git deve estar entre 0 e 300 segundos.')
    if not 10 <= check_interval <= 86400:
        raise AppError(
            422,
            'invalid_config',
            'Intervalo de verificação deve estar entre 10 segundos e 24 horas.',
        )
    if not 100 <= autosave_delay <= 10000:
        raise AppError(422, 'invalid_config', 'Autosave deve estar entre 100 e 10000 milissegundos.')

    boolean_options = (
        ('server', 'open_browser_on_start'),
        ('git', 'enabled'),
        ('github', 'enabled'),
        ('git', 'retry_enabled'),
        ('editor', 'autosave_enabled'),
        ('search', 'enabled'),
    )
    if any(not isinstance(config[section][key], bool) for section, key in boolean_options):
        raise AppError(422, 'invalid_config', 'As opções booleanas devem usar true ou false.')

    remote = config['git']['remote']
    branch = config['git']['branch']
    if not isinstance(remote, str) or not REMOTE_NAME_PATTERN.fullmatch(remote):
        raise AppError(422, 'invalid_config', 'Nome de remoto Git inválido.')
    if (
        not isinstance(branch, str)
        or not BRANCH_NAME_PATTERN.fullmatch(branch)
        or branch.startswith('-')
        or '..' in branch
    ):
        raise AppError(422, 'invalid_config', 'Nome de branch Git inválido.')

    repository_name = config['github']['repository_name']
    if (
        not isinstance(repository_name, str)
        or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', repository_name)
    ):
        raise AppError(422, 'invalid_config', 'Nome do repositório do GitHub inválido.')

    config['server']['port'] = port
    config['git']['sync_debounce_seconds'] = debounce
    config['git']['periodic_check_seconds'] = check_interval
    config['editor']['autosave_debounce_ms'] = autosave_delay


@api.get('/system/integrity')
def integrity():
    return check_integrity(PROJECTS)
