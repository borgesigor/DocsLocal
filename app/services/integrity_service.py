from pathlib import Path

from app.services import document_service as documents
from app.services import project_service as projects
from app.services.storage import repository_operation


@repository_operation
def check_integrity(projects_root: Path):
    issues = []
    folders = [
        folder for folder in projects_root.iterdir()
        if folder.is_dir() and not folder.is_symlink()
    ] if projects_root.exists() else []

    for folder in folders:
        def report(path, issue):
            issues.append({'project_id': folder.name, 'path': path, 'issue': issue})

        try:
            projects.load_project_metadata(folder)
        except (OSError, UnicodeError, ValueError) as error:
            report('project.toml', f'Invalid project metadata: {error}')

        index = folder / 'index.md'
        if not index.is_file() or index.is_symlink():
            report('index.md', 'Missing readable index.md')

        ids = set()
        for path in documents.iter_documents(folder):
            relative_path = path.relative_to(folder).as_posix()
            try:
                document_id, _, _ = documents.parse_document(path)
            except (OSError, UnicodeError) as error:
                report(relative_path, f'Unreadable document: {error}')
                continue
            if document_id in ids:
                report(relative_path, 'duplicate document id')
            ids.add(document_id)

    return {'ok': not issues, 'issues': issues, 'projects': len(folders)}
