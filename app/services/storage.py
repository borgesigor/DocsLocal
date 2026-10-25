import os
import tempfile
import threading
from functools import wraps
from pathlib import Path


# The application runs one worker and InstanceLock excludes a second server.
# Readers share this lock so Windows never replaces metadata while it is open.
REPOSITORY_LOCK = threading.RLock()


def repository_operation(operation):
    @wraps(operation)
    def synchronized(*args, **kwargs):
        with REPOSITORY_LOCK:
            return operation(*args, **kwargs)
    return synchronized


def atomic_write(path: Path, content: str | bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    is_binary = isinstance(content, bytes)
    mode = 'wb' if is_binary else 'w'
    options = {} if is_binary else {'encoding': 'utf-8', 'newline': ''}
    descriptor, temporary_path = tempfile.mkstemp(
        prefix='.docs-local-',
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, mode, **options) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
