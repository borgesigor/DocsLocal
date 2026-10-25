"""Restore and merge a managed backup, publishing only real file changes."""

import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote

from app.core.security import inside, validate_path_components
from app.services.storage import atomic_write, repository_operation
from app.services.sync_merge import blob_sha, merge_snapshots, snapshot_hashes

MANAGED_ROOT = 'docs-local-backup'
SYNC_ROOT = f'{MANAGED_ROOT}/data'
MARKER_PATH = f'{MANAGED_ROOT}/.docs-local-managed.json'
MARKER_CONTENT = b'{"managed_by":"docs-local","schema_version":1}\n'
LEGACY_MARKER_PATH = f'{SYNC_ROOT}/{MARKER_PATH}'
FILE_MODE = '100644'
MAX_BACKUP_BYTES = 250 * 1024 * 1024


def validate_backup_path(value: str) -> str:
    parts = value.split('/')
    if not value or '\\' in value or any(part.casefold() in {'', '.', '..', '.git'} for part in parts):
        raise RuntimeError('O backup contém um caminho inválido. Nenhum arquivo remoto foi alterado.')
    validate_path_components(tuple(parts))
    return PurePosixPath(value).as_posix()


@repository_operation
def local_snapshot(root: Path) -> dict[str, bytes]:
    root.mkdir(parents=True, exist_ok=True)
    snapshot = {}
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if '.git' in relative.parts or path.is_symlink() or not path.is_file():
            continue
        inside(root, path)
        snapshot[relative.as_posix()] = path.read_bytes()
    return snapshot


class BackupState:
    def __init__(self, folder: Path, repository_root: Path | None = None):
        self.folder = folder / 'github-sync'
        self.repository_root = str(repository_root.resolve()) if repository_root else ''

    def _read(self, name: str) -> dict:
        try:
            value = json.loads((self.folder / name).read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def session(self) -> dict:
        return self._read('session.json')

    def save_session(self, profile: dict, repository: dict | None) -> None:
        atomic_write(self.folder / 'session.json', json.dumps({'profile': profile, 'repository': repository}))

    def binding(self, repository: dict) -> str:
        return f"{repository['full_name']}:{repository.get('id', '')}:{repository.get('default_branch', 'main')}:{self.repository_root}"

    @staticmethod
    def _baseline_name(repository: str) -> str:
        return hashlib.sha256(repository.casefold().encode()).hexdigest() + '.json'

    def baseline(self, repository: str) -> dict[str, str]:
        values = self._read(self._baseline_name(repository)).get('files', {})
        if not isinstance(values, dict):
            return {}
        if any(not isinstance(path, str) or not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{40}', sha) for path, sha in values.items()):
            return {}
        return values

    def save_baseline(self, repository: str, files: dict[str, bytes]) -> None:
        atomic_write(self.folder / self._baseline_name(repository), json.dumps({'files': snapshot_hashes(files)}))

    def pending_paths(self, files: dict[str, bytes], repository: str | None = None) -> list[str]:
        if repository is None:
            cached = self.session().get('repository')
            repository = self.binding(cached) if cached else ''
        baseline = self.baseline(repository)
        current = snapshot_hashes(files)
        return sorted(path for path in baseline.keys() | current.keys() if baseline.get(path) != current.get(path))

    def record_pending(self, paths: list[str]) -> None:
        if self._read('outbox.json').get('paths') != paths:
            atomic_write(self.folder / 'outbox.json', json.dumps({'paths': paths}))


@dataclass
class BackupResult:
    conflicts: list[str]
    restored: bool
    uploaded_files: int


class BackupSync:
    def __init__(self, root: Path, state: BackupState, api, cancelled=lambda: False):
        self.root, self.state, self.api = root, state, api
        self.cancelled = cancelled

    def synchronize(self, repository: dict, token: str, get_reference) -> BackupResult:
        repository_path = '/repos/' + '/'.join(quote(part, safe='') for part in repository['full_name'].split('/'))
        branch = quote(repository['default_branch'], safe='/')
        reference = get_reference(repository_path, branch, token)
        parent_sha = reference['object']['sha']
        parent = self.api(f'{repository_path}/git/commits/{quote(parent_sha, safe="")}', token=token)
        base_tree = parent['tree']['sha']
        tree = self.api(f'{repository_path}/git/trees/{quote(base_tree, safe="")}?recursive=1', token=token)
        entries, legacy_marker = self._managed_entries(tree)
        self._known_blobs = {entry['sha'] for entry in tree['tree'] if entry.get('type') == 'blob'}
        initial = local_snapshot(self.root)
        remote = self._download_files(entries, initial, repository_path, token)
        binding = self.state.binding(repository)
        baseline = self.state.baseline(binding)
        local = self._without_default_guide_collision(initial, remote, baseline)
        plan = merge_snapshots(local, remote, baseline)

        # Restore before publishing; files edited during network I/O stay in the outbox.
        restored = self._apply_local(initial, plan.files)
        changes = self._upload_changes(plan.files, entries, repository_path, token)
        marker = next((entry for entry in tree['tree'] if entry.get('path') == MARKER_PATH), None)
        if marker is None:
            changes.append(self._upload_blob(MARKER_PATH, MARKER_CONTENT, repository_path, token))
        if legacy_marker:
            changes.append({'path': LEGACY_MARKER_PATH, 'mode': FILE_MODE, 'type': 'blob', 'sha': None})
        if changes:
            new_tree = self.api(f'{repository_path}/git/trees', method='POST', token=token,
                                data={'base_tree': base_tree, 'tree': changes})
            commit = self.api(f'{repository_path}/git/commits', method='POST', token=token, data={
                'message': 'docs: sincroniza documentos locais e backup',
                'tree': new_tree['sha'], 'parents': [parent_sha],
            })
            self.api(f'{repository_path}/git/refs/heads/{branch}', method='PATCH', token=token,
                     data={'sha': commit['sha'], 'force': False})
        self.state.save_baseline(binding, plan.files)
        self.state.record_pending(self.state.pending_paths(local_snapshot(self.root), binding))
        return BackupResult(plan.conflicts, restored, len(changes))

    @staticmethod
    def _without_default_guide_collision(local: dict, remote: dict, baseline: dict) -> dict:
        from app.services.onboarding_service import WELCOME_CONTENT
        from app.services.sync_merge import DOCUMENT_ID

        local = dict(local)
        guide = 'projetos/guia-do-docs-local/index.md'
        if guide in local and guide in remote and guide not in baseline:
            metadata = DOCUMENT_ID.match(local[guide])
            if metadata and local[guide][metadata.end():].replace(b'\r\n', b'\n') == WELCOME_CONTENT.encode():
                local.pop(guide)
                local.pop('projetos/guia-do-docs-local/project.toml', None)
        return local

    @staticmethod
    def _managed_entries(tree: dict) -> tuple[dict, bool]:
        if tree.get('truncated'):
            raise RuntimeError('O repositório tem arquivos demais para uma sincronização segura.')
        all_entries = tree.get('tree', [])
        markers = {entry['path']: entry for entry in all_entries if entry.get('path') in {MARKER_PATH, LEGACY_MARKER_PATH}}
        marker_sha = blob_sha(MARKER_CONTENT)
        if any(entry.get('type') != 'blob' or entry.get('sha') != marker_sha for entry in markers.values()):
            raise RuntimeError('O marcador do backup é inválido. Nenhum arquivo foi alterado.')
        files, names = {}, set()
        for entry in all_entries:
            remote_path = entry.get('path', '')
            if not remote_path.startswith(SYNC_ROOT + '/') or remote_path == LEGACY_MARKER_PATH:
                continue
            path = validate_backup_path(remote_path[len(SYNC_ROOT) + 1:])
            if entry.get('type') == 'tree':
                continue
            if entry.get('type') != 'blob' or entry.get('mode') not in {'100644', '100755'}:
                raise RuntimeError('O backup contém links ou arquivos não suportados.')
            if path.casefold() in names:
                raise RuntimeError('O backup contém nomes de arquivos que colidem no Windows.')
            names.add(path.casefold())
            files[path] = entry
        if files and not markers:
            raise RuntimeError('Já existem arquivos sem um marcador válido. O app não vai sobrescrever esse backup.')
        return files, LEGACY_MARKER_PATH in markers

    def _download_files(self, entries: dict, local: dict, repository_path: str, token: str) -> dict:
        blobs = {blob_sha(content): content for content in local.values()}
        remote, total = {}, 0
        for path, entry in entries.items():
            sha = entry['sha']
            if sha not in blobs:
                blob = self.api(f'{repository_path}/git/blobs/{quote(sha, safe="")}', token=token)
                if blob.get('encoding') != 'base64':
                    raise RuntimeError('O GitHub retornou um arquivo com codificação inválida.')
                try:
                    content = base64.b64decode(''.join(blob['content'].split()), validate=True)
                except (ValueError, KeyError, TypeError):
                    raise RuntimeError('O GitHub retornou um arquivo inválido.')
                if blob_sha(content) != sha:
                    raise RuntimeError('A integridade de um arquivo do backup não pôde ser verificada.')
                blobs[sha] = content
            remote[path] = blobs[sha]
            total += len(blobs[sha])
            if total > MAX_BACKUP_BYTES:
                raise RuntimeError('O backup excede o limite de tamanho para restauração segura.')
        return remote

    @repository_operation
    def _apply_local(self, initial: dict, merged: dict) -> bool:
        if self.cancelled():
            raise RuntimeError('Sincronização interrompida para atualização. Os arquivos continuam na fila local.')
        paths = initial.keys() | merged.keys()
        names = {}
        for path in paths:
            key = path.casefold()
            if key in names and names[key] != path:
                raise RuntimeError('Os nomes de arquivos locais e remotos colidem no Windows. Renomeie o arquivo local para sincronizar.')
            names[key] = path
        destinations = {path: inside(self.root, self.root / validate_backup_path(path)) for path in paths}
        changed = False
        for path, destination in destinations.items():
            current = destination.read_bytes() if destination.is_file() else None
            if current != initial.get(path) or current == merged.get(path):
                continue
            if path in merged:
                atomic_write(destination, merged[path])
            else:
                destination.unlink(missing_ok=True)
            changed = True
        return changed

    def _upload_blob(self, path: str, content: bytes, repository_path: str, token: str) -> dict:
        sha = blob_sha(content)
        if sha not in self._known_blobs:
            blob = self.api(f'{repository_path}/git/blobs', method='POST', token=token,
                            data={'content': base64.b64encode(content).decode('ascii'), 'encoding': 'base64'})
            if blob['sha'] != sha:
                raise RuntimeError('O GitHub não confirmou a integridade do arquivo enviado.')
            self._known_blobs.add(sha)
        return {'path': path, 'mode': FILE_MODE, 'type': 'blob', 'sha': sha}

    def _upload_changes(self, files: dict, entries: dict, repository_path: str, token: str) -> list[dict]:
        changes = []
        for path, entry in entries.items():
            if path not in files:
                changes.append({'path': f'{SYNC_ROOT}/{path}', 'mode': entry['mode'], 'type': 'blob', 'sha': None})
        for path, content in files.items():
            if blob_sha(content) != entries.get(path, {}).get('sha'):
                changes.append(self._upload_blob(f'{SYNC_ROOT}/{path}', content, repository_path, token))
        return changes
