"""Walk user project files without following links or entering Git internals."""

import os
from pathlib import Path


def iter_project_entries(root: Path):
    for directory, folders, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        folders[:] = [name for name in folders
                      if name.casefold() != '.git' and not (parent / name).is_symlink()]
        for name in folders + files:
            path = parent / name
            if not path.is_symlink():
                yield path


def iter_markdown_files(root: Path):
    index = root / 'index.md'
    if index.is_file() and not index.is_symlink():
        yield index
    for path in iter_project_entries(root):
        if path != index and path.is_file() and path.suffix.casefold() == '.md':
            yield path
