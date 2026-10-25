"""Plan a lossless three-way merge of local files and a GitHub backup."""

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
import tomllib
import uuid

DOCUMENT_ID = re.compile(rb'^(<!-- docs-local: id=)([\w-]+)( revision=\d+ updated=[^ ]+ -->\r?\n)')


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(f'blob {len(content)}\0'.encode('ascii') + content).hexdigest()


def snapshot_hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {path: blob_sha(content) for path, content in files.items()}


@dataclass
class MergeResult:
    files: dict[str, bytes]
    conflicts: list[str]


def _document_identity(path: str, content: bytes) -> tuple[str, bytes] | None:
    match = DOCUMENT_ID.match(content) if path.endswith('.md') else None
    if match is None:
        return None
    parts = PurePosixPath(path).parts
    project = '/'.join(parts[:2]) if parts[0] == 'projetos' else ''
    return project, match[2]


def _equivalent(path: str, local: bytes, remote: bytes) -> bool:
    local_metadata = DOCUMENT_ID.match(local) if path.endswith('.md') else None
    remote_metadata = DOCUMENT_ID.match(remote) if path.endswith('.md') else None
    if local_metadata and remote_metadata:
        return local[local_metadata.end():].replace(b'\r\n', b'\n') == remote[remote_metadata.end():].replace(b'\r\n', b'\n')
    if PurePosixPath(path).name == 'project.toml':
        try:
            projects = [tomllib.loads(content.decode('utf-8')) for content in (local, remote)]
        except (ValueError, UnicodeError):
            return False
        for project in projects:
            project.pop('created_at', None)
            project.pop('updated_at', None)
        return projects[0] == projects[1]
    return local == remote


def _align_document_moves(local: dict, remote: dict, baseline: dict) -> None:
    remote_ids = {
        identity: path for path, content in sorted(remote.items())
        if (identity := _document_identity(path, content)) is not None
    }
    for local_path, content in list(local.items()):
        identity = _document_identity(local_path, content)
        remote_path = remote_ids.get(identity)
        if remote_path is None or remote_path == local_path or remote_path in local:
            continue
        if baseline.get(remote_path) == blob_sha(remote[remote_path]):
            # The remote path has not moved; this is a queued local rename.
            continue
        local[remote_path] = local.pop(local_path)
        if local_path in baseline:
            baseline[remote_path] = baseline.pop(local_path)


def _conflict_copy(path: str, content: bytes, occupied: dict[str, bytes]) -> tuple[str, bytes]:
    original = PurePosixPath(path)
    digest = blob_sha(content)[:12]
    name = f'{original.stem}.conflito-local-{digest}{original.suffix}'
    if original.name == 'index.md' and len(original.parts) == 3 and original.parts[0] == 'projetos':
        destination = original.parent / 'docs' / 'conflitos' / name
    else:
        destination = original.with_name(name)
    match = DOCUMENT_ID.match(content) if original.suffix == '.md' else None
    if match:
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, f'docs-local-conflict:{path}:{digest}')).encode()
        content = match[1] + identity + match[3] + content[match.end():]
    candidate = destination
    suffix = 2
    while candidate.as_posix() in occupied and occupied[candidate.as_posix()] != content:
        candidate = destination.with_name(f'{destination.stem}-{suffix}{destination.suffix}')
        suffix += 1
    return candidate.as_posix(), content


def merge_snapshots(local: dict[str, bytes], remote: dict[str, bytes], baseline: dict[str, str]) -> MergeResult:
    local, baseline = dict(local), dict(baseline)
    _align_document_moves(local, remote, baseline)
    merged: dict[str, bytes] = {}
    occupied = {**remote, **local}
    conflicts: list[str] = []
    for path in sorted(local.keys() | remote.keys() | baseline.keys()):
        local_content, remote_content = local.get(path), remote.get(path)
        local_sha = blob_sha(local_content) if local_content is not None else None
        remote_sha = blob_sha(remote_content) if remote_content is not None else None
        previous_sha = baseline.get(path)
        if local_sha == remote_sha or local_sha == previous_sha:
            chosen = remote_content
        elif remote_sha == previous_sha or remote_content is None:
            chosen = local_content
        elif local_content is None:
            chosen = remote_content
        elif _equivalent(path, local_content, remote_content):
            chosen = remote_content
        else:
            chosen = remote_content
            conflict_path, conflict_content = _conflict_copy(path, local_content, occupied)
            merged[conflict_path] = conflict_content
            occupied[conflict_path] = conflict_content
            conflicts.append(conflict_path)
        if chosen is not None:
            merged[path] = chosen

    # A retry or a move must not introduce two files with the same document ID.
    identities: dict[tuple[str, bytes], str] = {}
    for path in sorted(merged, key=lambda value: (value not in remote, value)):
        identity = _document_identity(path, merged[path])
        if identity is None:
            continue
        existing = identities.get(identity)
        if existing is None:
            identities[identity] = path
        elif _equivalent(path, merged[path], merged[existing]):
            del merged[path]
        else:
            conflict_path, conflict_content = _conflict_copy(path, merged.pop(path), merged)
            merged[conflict_path] = conflict_content
            conflicts.append(conflict_path)
    return MergeResult(merged, sorted(set(conflicts)))
