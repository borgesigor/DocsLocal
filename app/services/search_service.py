from app.services.document_service import (
    document_title,
    readable_documents,
)
from app.services.project_service import get_folder, list_projects
from app.core.exceptions import AppError
from app.services.storage import repository_operation

@repository_operation
def search(query: str, project_id: str | None = None):
    normalized_query = query.casefold().strip()
    if not normalized_query:
        raise AppError(422, 'empty_query', 'Informe um texto para pesquisar.')

    projects = [get_project(project_id)] if project_id else list_projects()
    results = []
    for project in projects:
        folder, _ = get_folder(project['id'])
        for path, (_, _, content) in readable_documents(folder):
            if normalized_query not in content.casefold():
                continue

            lines = content.splitlines()
            matching_line = next(
                (
                    index
                    for index, line in enumerate(lines)
                    if normalized_query in line.casefold()
                ),
                0,
            )
            snippet = ' '.join(lines[matching_line].strip().split())
            if len(snippet) > 240:
                snippet = snippet[:237] + '...'

            results.append(
                {
                    'project_id': project['id'],
                    'project_name': project['name'],
                    'path': path.relative_to(folder).as_posix(),
                    'title': document_title(content),
                    'snippet': snippet,
                }
            )
    return results

def get_project(project_id):
    project = next(
        (item for item in list_projects() if item['id'] == project_id),
        None,
    )
    if project is None:
        raise AppError(404, 'project_not_found', 'Projeto não encontrado.')
    return project
