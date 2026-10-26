"""Identities reserved for documentation shipped with the application."""

SYSTEM_PROJECT_IDS = frozenset({'guia-do-docs-local'})


def is_system_project_path(path: str) -> bool:
    parts = path.replace('\\', '/').casefold().split('/')
    return len(parts) >= 2 and parts[0] == 'projetos' and parts[1] in SYSTEM_PROJECT_IDS
