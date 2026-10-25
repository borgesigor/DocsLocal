import re
from pathlib import Path

from .exceptions import AppError

WINDOWS_INVALID_NAME_CHARACTERS = re.compile(r'[<>:"|?*\x00-\x1f\x7f-\x9f]')
WINDOWS_RESERVED_NAMES = re.compile(
    r'^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|CLOCK\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?$',
    re.IGNORECASE,
)


def validate_path_components(parts: tuple[str, ...]) -> None:
    for part in parts:
        if (
            WINDOWS_INVALID_NAME_CHARACTERS.search(part)
            or part.endswith((' ', '.'))
            or WINDOWS_RESERVED_NAMES.fullmatch(part)
        ):
            raise AppError(
                422,
                'invalid_path',
                'O caminho contém caracteres ou nomes reservados pelo Windows.',
            )

def safe_slug(value: str) -> str:
    slug = re.sub('[^a-z0-9]+', '-', value.casefold()).strip('-')
    if not slug or len(slug) > 80:
        raise AppError(422, 'invalid_slug', 'O nome precisa gerar um identificador válido.')
    return slug

def inside(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise AppError(400, 'invalid_path', 'O caminho solicitado sai da pasta autorizada.')

    cur = candidate
    while cur != root and cur != cur.parent:
        if cur.is_symlink():
            raise AppError(400, 'symlink_blocked', 'Caminhos com links simbólicos não são permitidos.')
        cur = cur.parent
    return resolved

def relative_doc_path(value: str) -> Path:
    p = Path(value.replace('\\', '/'))
    if p.is_absolute() or any(part in {'..', '.'} for part in p.parts) or not p.parts:
        raise AppError(422, 'invalid_path', 'Use um caminho relativo dentro do projeto.')
    validate_path_components(p.parts)
    return p

def document_path(root: Path, value: str) -> Path:
    """Resolve a document path while keeping documents in the Markdown area."""
    relative_path = relative_doc_path(value)

    if relative_path.as_posix().casefold() == 'index.md':
        relative_path = Path('index.md')
    elif relative_path.parts[0] != 'docs':
        raise AppError(422, 'invalid_path', 'Documentos devem ficar em index.md ou na pasta docs/.')

    if relative_path.suffix.casefold() != '.md':
        relative_path = relative_path.with_suffix('.md')
    elif relative_path.suffix != '.md':
        relative_path = relative_path.with_suffix('.md')

    if relative_path.as_posix() != 'index.md' and len(relative_path.parts) < 2:
        raise AppError(422, 'invalid_path', 'Informe um nome de arquivo dentro de docs/.')
    return inside(root, root / relative_path)

def project_folder_path(root: Path, value: str) -> Path:
    """Resolve a user-managed folder path inside docs/."""
    relative_path = relative_doc_path(value)
    if relative_path.parts[0] != 'docs':
        raise AppError(422, 'invalid_path', 'Pastas devem ficar dentro de docs/.')
    if len(relative_path.parts) < 2:
        raise AppError(422, 'invalid_path', 'Não é possível alterar a pasta docs/.')
    return inside(root, root / relative_path)
