from datetime import datetime, timezone
from pathlib import Path
import hashlib
import re
import uuid

from app.core.exceptions import AppError
from app.core.security import document_path, inside, project_folder_path
from app.services.project_service import get_folder, now
from app.services.storage import atomic_write, repository_operation

DOCUMENT_METADATA = re.compile(
    r'^<!-- docs-local: id=([\w-]+) revision=(\d+) updated=([^ ]+) -->\n'
)


def parse_document(path: Path):
    raw_content = path.read_text(encoding='utf-8')
    metadata = DOCUMENT_METADATA.match(raw_content)
    if metadata:
        document_id = metadata.group(1)
        revision = int(metadata.group(2))
        content = raw_content[metadata.end():]
        return document_id, revision, content

    # Legacy Markdown without metadata receives a deterministic ID from its path.
    document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(path.resolve())))
    return document_id, 1, raw_content


def serialize_document(document_id: str, revision: int, content: str):
    updated_at = now()
    return (
        f'<!-- docs-local: id={document_id} revision={revision} updated={updated_at} -->\n'
        f'{content}'
    )


def iter_documents(project_folder: Path):
    documents_root = project_folder / 'docs'
    candidates = [project_folder / 'index.md', *documents_root.rglob('*.md')]

    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        try:
            inside(project_folder, path)
        except AppError:
            continue
        yield path


def document_title(content: str):
    for line in content.splitlines():
        if line.startswith('# '):
            return line[2:].strip()
    return 'Sem título'


def readable_documents(project_folder: Path):
    for path in iter_documents(project_folder):
        try:
            parsed = parse_document(path)
        except (OSError, UnicodeError):
            # Integrity reports these paths; never rewrite damaged content.
            continue
        yield path, parsed


@repository_operation
def list_documents(project_id: str):
    project_folder, _ = get_folder(project_id)
    documents = []

    for path, (document_id, revision, content) in readable_documents(project_folder):
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        documents.append(
            {
                'id': document_id,
                'path': path.relative_to(project_folder).as_posix(),
                'title': document_title(content),
                'revision': revision,
                'updated_at': modified_at,
            }
        )
    return documents


def find_document(project_folder: Path, document_id: str):
    for path, (current_id, revision, content) in readable_documents(project_folder):
        if current_id == document_id:
            return path, revision, content
    raise AppError(404, 'document_not_found', 'Documento não encontrado.')


@repository_operation
def create_document(project_id: str, path: str, title: str = 'Sem título', content: str | None = None):
    project_folder, _ = get_folder(project_id)
    destination = document_path(project_folder, path)
    if destination.exists():
        raise AppError(409, 'path_exists', 'Já existe um documento nesse caminho.')

    destination.parent.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid.uuid4())
    document_content = content if content is not None else f'# {title}\n\n'
    atomic_write(destination, serialize_document(document_id, 1, document_content))
    from app.services.project_service import touch_project
    try:
        touch_project(project_id)
    except Exception:
        destination.unlink()
        raise
    return read_document(project_id, document_id)


@repository_operation
def read_document(project_id: str, document_id: str):
    project_folder, _ = get_folder(project_id)
    path, revision, content = find_document(project_folder, document_id)
    etag = hashlib.sha256(f'{document_id}:{revision}'.encode()).hexdigest()
    return {
        'id': document_id,
        'path': path.relative_to(project_folder).as_posix(),
        'title': document_title(content),
        'content': content,
        'revision': revision,
        'etag': etag,
    }


@repository_operation
def update_document(
    project_id: str,
    document_id: str,
    content: str,
    expected_revision: int | None = None,
    new_path: str | None = None,
):
    project_folder, _ = get_folder(project_id)
    current_path, current_revision, _ = find_document(project_folder, document_id)
    if expected_revision is not None and expected_revision != current_revision:
        raise AppError(
            409,
            'revision_conflict',
            f'Revisão atual {current_revision}; recarregue antes de salvar.',
        )

    destination = document_path(project_folder, new_path) if new_path else current_path
    if current_path == project_folder / 'index.md' and destination != current_path:
        raise AppError(400, 'protected_document', 'O documento inicial não pode ser movido.')
    if destination != current_path and destination.exists():
        raise AppError(409, 'path_exists', 'Já existe um documento nesse caminho.')

    destination.parent.mkdir(parents=True, exist_ok=True)
    next_revision = current_revision + 1
    original_bytes = current_path.read_bytes()
    atomic_write(
        destination,
        serialize_document(document_id, next_revision, content),
    )
    from app.services.project_service import touch_project
    try:
        if destination != current_path:
            current_path.unlink()
        touch_project(project_id)
    except Exception:
        atomic_write(current_path, original_bytes)
        if destination != current_path:
            destination.unlink()
        raise
    return read_document(project_id, document_id)


@repository_operation
def delete_document(project_id: str, document_id: str):
    project_folder, _ = get_folder(project_id)
    path, _, _ = find_document(project_folder, document_id)
    if path == project_folder / 'index.md':
        raise AppError(400, 'protected_document', 'O documento inicial não pode ser excluído.')

    original_bytes = path.read_bytes()
    path.unlink()
    from app.services.project_service import touch_project
    try:
        touch_project(project_id)
    except Exception:
        atomic_write(path, original_bytes)
        raise
    return {'deleted': True, 'id': document_id}


@repository_operation
def tree(project_id: str):
    project_folder, _ = get_folder(project_id)
    nodes = {}
    docs_root = project_folder / 'docs'

    for directory in docs_root.rglob('*'):
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            inside(project_folder, directory)
        except AppError:
            continue

        parent = nodes
        for part in directory.relative_to(project_folder).parts:
            folder_node = parent.setdefault(
                part,
                {'type': 'folder', 'name': part, 'children': {}},
            )
            parent = folder_node['children']

    for path, (document_id, revision, content) in readable_documents(project_folder):
        relative_path = path.relative_to(project_folder).as_posix()
        parent = nodes
        parts = relative_path.split('/')
        for part in parts[:-1]:
            folder_node = parent.setdefault(
                part,
                {'type': 'folder', 'name': part, 'children': {}},
            )
            parent = folder_node['children']

        parent[parts[-1]] = {
            'type': 'document',
            'id': document_id,
            'name': parts[-1],
            'title': document_title(content),
            'path': relative_path,
            'revision': revision,
        }

    def serialize_nodes(children):
        ordered_nodes = sorted(children.items(), key=lambda item: item[0].casefold())
        result = []
        for _, node in ordered_nodes:
            if node['type'] == 'folder':
                result.append({**node, 'children': serialize_nodes(node['children'])})
            else:
                result.append(node)
        return result

    return serialize_nodes(nodes)


@repository_operation
def create_folder(project_id: str, path: str):
    project_folder, _ = get_folder(project_id)
    folder_path = project_folder_path(project_folder, path)
    if folder_path.exists():
        raise AppError(409, 'path_exists', 'Já existe uma pasta nesse caminho.')

    folder_path.mkdir(parents=True, exist_ok=True)
    atomic_write(folder_path / '.gitkeep', '')
    from app.services.project_service import touch_project
    touch_project(project_id)
    return {'path': folder_path.relative_to(project_folder).as_posix()}
