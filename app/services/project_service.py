from datetime import datetime, timezone
from pathlib import Path
import tomllib
import uuid
import shutil

from app.core.config import PROJECTS
from app.core.exceptions import AppError
from app.core.security import inside, safe_slug, validate_path_components
from app.services.storage import atomic_write, repository_operation
from app.services.toml_writer import dumps_values


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@repository_operation
def load_project_metadata(folder: Path):
    with (folder / 'project.toml').open('rb') as project_file:
        project = tomllib.load(project_file)
    if any(not isinstance(project.get(field), str) or not project[field] for field in ('id', 'name', 'slug')):
        raise ValueError('Missing or invalid project id, name or slug')
    if project['id'] != folder.name or project['slug'] != folder.name:
        raise ValueError('Project id/slug does not match directory')
    if not isinstance(project.get('archived', False), bool):
        raise ValueError('Invalid archived flag')
    return project


@repository_operation
def read_project(folder: Path):
    try:
        project = load_project_metadata(folder)
    except (OSError, UnicodeError, ValueError):
        return None
    if project.get('archived', False):
        return None
    return project


@repository_operation
def list_projects(include_archived: bool = False):
    PROJECTS.mkdir(parents=True, exist_ok=True)
    projects = []

    for folder in PROJECTS.iterdir():
        if not folder.is_dir() or folder.is_symlink():
            continue

        try:
            project = load_project_metadata(folder)
        except (OSError, UnicodeError, ValueError):
            continue

        if project.get('archived', False) and not include_archived:
            continue

        docs_folder = folder / 'docs'
        document_count = sum(
            1
            for document in docs_folder.rglob('*.md')
            if document.is_file() and not document.is_symlink()
        )
        document_count += int((folder / 'index.md').is_file())
        projects.append({**project, 'document_count': document_count})

    return sorted(projects, key=lambda project: project['name'].casefold())


@repository_operation
def get_folder(project_id: str, include_archived: bool = False):
    allowed_characters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'
    if not project_id or any(character not in allowed_characters for character in project_id):
        raise AppError(404, 'project_not_found', 'Projeto não encontrado.')

    folder = inside(PROJECTS, PROJECTS / project_id)
    project = read_project(folder)
    if project is None and include_archived:
        try:
            project = load_project_metadata(folder)
        except (OSError, UnicodeError, ValueError):
            project = None

    if project is None:
        raise AppError(404, 'project_not_found', 'Projeto não encontrado.')
    return folder, project


@repository_operation
def create_project(name: str, description: str = ''):
    slug_base = safe_slug(name)
    validate_path_components((slug_base,))
    PROJECTS.mkdir(parents=True, exist_ok=True)
    for suffix in range(1, 10001):
        slug = slug_base if suffix == 1 else f'{slug_base}-{suffix}'
        folder = PROJECTS / slug
        try:
            folder.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise AppError(409, 'project_name_exhausted', 'Escolha outro nome para o projeto.')

    try:
        return initialize_project(folder, slug, name, description)
    except Exception:
        shutil.rmtree(folder)
        raise


def initialize_project(folder: Path, slug: str, name: str, description: str):
    (folder / 'docs').mkdir()
    (folder / 'assets').mkdir()

    created_at = now()
    project = {
        'id': slug,
        'slug': slug,
        'name': name.strip(),
        'description': description,
        'created_at': created_at,
        'updated_at': created_at,
        'archived': False,
    }
    atomic_write(folder / 'project.toml', dumps_values(project))

    document_id = uuid.uuid4()
    index_content = (
        f'<!-- docs-local: id={document_id} revision=1 updated={created_at} -->\n'
        f'# {name.strip()}\n\n{description.strip()}\n'
    )
    atomic_write(folder / 'index.md', index_content)
    atomic_write(folder / 'docs' / '.gitkeep', '')
    atomic_write(folder / 'assets' / '.gitkeep', '')
    return {**project, 'document_count': 1}


@repository_operation
def update_project(project_id: str, patch: dict):
    folder, project = get_folder(project_id, include_archived=True)

    for field in ('name', 'description', 'archived'):
        if field in patch and patch[field] is not None:
            value = patch[field]
            if field == 'name':
                value = value.strip()
                if not value:
                    raise AppError(
                        422,
                        'invalid_project_name',
                        'O nome do projeto não pode ficar vazio.',
                    )
            project[field] = value

    project['updated_at'] = now()
    atomic_write(folder / 'project.toml', dumps_values(project))
    return project


def touch_project(project_id: str):
    return update_project(project_id, {})


def delete_project(project_id: str):
    return update_project(project_id, {'archived': True})
