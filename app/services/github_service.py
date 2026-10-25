"""GitHub OAuth, repository setup, and REST-based documentation sync."""

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import quote, urlencode

from app.core.config import CONFIG, DATA, REPO, STATE
from app.core.exceptions import AppError
from app.services.github_client import GitHubAPIError, github_api, oauth_request
from app.services.secret_store import secret_store
from app.services.storage import atomic_write, repository_operation
from app.services.toml_writer import dumps as write_toml

MANAGED_ROOT = 'docs-local-backup'
SYNC_ROOT = f'{MANAGED_ROOT}/data'
MARKER_PATH = f'{MANAGED_ROOT}/.docs-local-managed.json'
MARKER_CONTENT = b'{"managed_by":"docs-local","schema_version":1}\n'
AUTHORIZATION_CALLBACK_PATH = '/api/v1/github/auth/callback'
AUTHORIZATION_MAX_AGE_SECONDS = 600
GITHUB_FILE_MODE = '100644'


@dataclass
class OAuthAttempt:
    state: str
    verifier: str
    created_at: float


class GitHubSync:
    """Queue local snapshots and publish them with GitHub's REST Git API."""

    def __init__(self):
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self.worker: asyncio.Task | None = None
        self.status = {
            'state': 'unauthenticated',
            'last_sync': None,
            'last_error': None,
            'pending': False,
            'retry_count': 0,
        }
        self._auth_lock = threading.RLock()
        self._oauth_attempt: OAuthAttempt | None = None

    @staticmethod
    def callback_url() -> str:
        host = CONFIG['server']['host']
        host = '127.0.0.1' if host == 'localhost' else host
        if host == '::1':
            host = '[::1]'
        return f"http://{host}:{CONFIG['server']['port']}{AUTHORIZATION_CALLBACK_PATH}"

    def is_configured(self) -> bool:
        return bool(
            CONFIG['github'].get('client_id', '').strip()
            and secret_store.get('client_secret')
        )

    def is_authenticated(self) -> bool:
        return bool(secret_store.get('access_token'))

    def configure_oauth(self, client_id: str, client_secret: str) -> dict:
        client_id = client_id.strip()
        client_secret = client_secret.strip()
        if not client_id or len(client_id) > 200:
            raise AppError(422, 'invalid_github_client_id', 'Informe um Client ID válido.')
        if not client_secret or len(client_secret) > 500:
            raise AppError(422, 'invalid_github_client_secret', 'Informe um Client Secret válido.')

        CONFIG['github']['client_id'] = client_id
        CONFIG['github']['enabled'] = True
        atomic_write(DATA / 'config.toml', write_toml(CONFIG))
        secret_store.write(client_secret=client_secret)
        return {'configured': True, 'callback_url': self.callback_url()}

    def start_authorization(self) -> str:
        self._require_oauth_configuration()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode('ascii')).digest()
        ).decode('ascii').rstrip('=')
        self._oauth_attempt = OAuthAttempt(state, verifier, time.monotonic())

        query = urlencode(
            {
                'client_id': CONFIG['github']['client_id'],
                'redirect_uri': self.callback_url(),
                'scope': 'repo read:user',
                'state': state,
                'code_challenge': challenge,
                'code_challenge_method': 'S256',
            }
        )
        return f'https://github.com/login/oauth/authorize?{query}'

    def complete_authorization(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None = None,
    ) -> None:
        attempt = self._oauth_attempt
        self._oauth_attempt = None
        if (
            attempt is None
            or not state
            or not secrets.compare_digest(attempt.state, state)
            or time.monotonic() - attempt.created_at > AUTHORIZATION_MAX_AGE_SECONDS
        ):
            raise AppError(400, 'invalid_oauth_state', 'A autorização expirou ou não é válida.')
        if error:
            raise AppError(400, 'github_authorization_denied', 'O acesso ao GitHub foi cancelado.')
        if not code:
            raise AppError(400, 'missing_oauth_code', 'O GitHub não retornou o código de autorização.')

        token_response = oauth_request(
            'access_token',
            {
                'client_id': CONFIG['github']['client_id'],
                'client_secret': secret_store.get('client_secret') or '',
                'code': code,
                'redirect_uri': self.callback_url(),
                'code_verifier': attempt.verifier,
            },
        )
        access_token = token_response.get('access_token')
        if not isinstance(access_token, str) or not access_token:
            raise AppError(502, 'github_token_missing', 'O GitHub não retornou um token de acesso.')

        token_data = self._token_storage_values(token_response)
        secret_store.write(**token_data)
        profile = github_api('/user', token=access_token)
        if not profile.get('login'):
            secret_store.write(access_token=None, refresh_token=None, expires_at=None)
            raise AppError(502, 'github_profile_missing', 'Não foi possível carregar a conta do GitHub.')

        try:
            self._ensure_repository(profile, access_token)
            repo_error = None
        except (GitHubAPIError, RuntimeError) as setup_error:
            repo_error = self._safe_error_message(setup_error)

        self.status.update(
            state='idle' if repo_error is None else 'error',
            pending=False,
            last_error=repo_error,
        )

    @staticmethod
    def _token_storage_values(response: dict) -> dict[str, str | None]:
        values: dict[str, str | None] = {
            'access_token': response.get('access_token'),
            'refresh_token': response.get('refresh_token'),
            'expires_at': None,
        }
        expires_in = response.get('expires_in')
        if expires_in:
            try:
                values['expires_at'] = str(int(time.time() + int(expires_in)))
            except (TypeError, ValueError):
                pass
        return values

    def logout(self) -> None:
        secret_store.write(
            access_token=None,
            refresh_token=None,
            expires_at=None,
        )
        self.status.update(
            state='unauthenticated',
            pending=False,
            last_error=None,
        )

    async def authentication_status(self) -> dict:
        if not self.is_authenticated():
            return {
                'configured': self.is_configured(),
                'authenticated': False,
                'client_id': CONFIG['github'].get('client_id', ''),
                'callback_url': self.callback_url(),
                'user': None,
                'repository': None,
                'repository_error': None,
            }

        try:
            profile = await asyncio.to_thread(self._profile)
        except GitHubAPIError as error:
            if error.status_code == 401:
                self.logout()
                return {
                    'configured': self.is_configured(),
                    'authenticated': False,
                    'client_id': CONFIG['github'].get('client_id', ''),
                    'callback_url': self.callback_url(),
                    'user': None,
                    'repository': None,
                    'repository_error': 'A sessão expirou. Entre novamente.',
                }
            raise AppError(502, 'github_status_failed', self._safe_error_message(error))

        try:
            token = await asyncio.to_thread(self._access_token)
            repository = await asyncio.to_thread(
                self._ensure_repository,
                profile,
                token,
            )
            repository_error = None
        except (GitHubAPIError, RuntimeError) as error:
            repository = None
            repository_error = self._safe_error_message(error)

        return {
            'configured': self.is_configured(),
            'authenticated': True,
            'client_id': CONFIG['github'].get('client_id', ''),
            'callback_url': self.callback_url(),
            'user': self._public_profile(profile),
            'repository': repository,
            'repository_error': repository_error,
        }

    def _profile(self) -> dict:
        token = self._access_token()
        return github_api('/user', token=token)

    @staticmethod
    def _public_profile(profile: dict) -> dict:
        return {
            'login': profile.get('login', ''),
            'name': profile.get('name'),
            'avatar_url': profile.get('avatar_url'),
            'html_url': profile.get('html_url'),
        }

    def _require_oauth_configuration(self) -> None:
        if not self.is_configured():
            raise AppError(
                503,
                'github_oauth_not_configured',
                'Configure o Client ID e o Client Secret do OAuth App do GitHub.',
            )

    def _access_token(self) -> str:
        with self._auth_lock:
            token = secret_store.get('access_token')
            if not token:
                raise GitHubAPIError(401, 'Entre na sua conta do GitHub.')

            expires_at = secret_store.get('expires_at')
            if not expires_at or int(expires_at) > int(time.time()) + 60:
                return token

            refresh_token = secret_store.get('refresh_token')
            if not refresh_token:
                secret_store.write(access_token=None, expires_at=None)
                raise GitHubAPIError(401, 'A sessão do GitHub expirou. Entre novamente.')

            response = oauth_request(
                'access_token',
                {
                    'client_id': CONFIG['github']['client_id'],
                    'client_secret': secret_store.get('client_secret') or '',
                    'grant_type': 'refresh_token',
                    'refresh_token': refresh_token,
                },
            )
            access_token = response.get('access_token')
            if not isinstance(access_token, str) or not access_token:
                secret_store.write(access_token=None, refresh_token=None, expires_at=None)
                raise GitHubAPIError(401, 'A sessão do GitHub expirou. Entre novamente.')
            secret_store.write(**self._token_storage_values(response))
            return access_token

    def _ensure_repository(self, profile: dict, token: str) -> dict:
        owner = profile.get('login')
        repository_name = CONFIG['github']['repository_name'].strip()
        if not owner or not repository_name:
            raise RuntimeError('A conta ou o nome do repositório do GitHub é inválido.')

        owner_path = quote(owner, safe='')
        repository_path = quote(repository_name, safe='')
        endpoint = f'/repos/{owner_path}/{repository_path}'
        try:
            repository = github_api(endpoint, token=token)
        except GitHubAPIError as error:
            if error.status_code != 404:
                raise
            try:
                repository = github_api(
                    '/user/repos',
                    method='POST',
                    token=token,
                    data={
                        'name': repository_name,
                        'description': 'Backup privado do Docs Local.',
                        'private': True,
                        'auto_init': True,
                    },
                )
            except GitHubAPIError as create_error:
                if create_error.status_code != 422:
                    raise
                repository = github_api(endpoint, token=token)

        repository_owner = repository.get('owner', {}).get('login', '')
        if repository_owner.casefold() != owner.casefold():
            raise RuntimeError('O repositório configurado não pertence à conta conectada.')
        if not repository.get('private', False):
            raise RuntimeError(
                'O repositório de backup precisa ser privado. Torne-o privado no GitHub e tente novamente.'
            )

        return {
            'name': repository.get('name', repository_name),
            'full_name': repository.get('full_name', f'{owner}/{repository_name}'),
            'html_url': repository.get('html_url'),
            'default_branch': repository.get('default_branch') or 'main',
        }

    async def authentication_callback(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None = None,
    ) -> None:
        await asyncio.to_thread(
            self.complete_authorization,
            code=code,
            state=state,
            error=error,
        )
        if self.status.get('state') == 'idle':
            await self.trigger(0)

    def start(self) -> None:
        worker_is_running = self.worker is not None and not self.worker.done()
        if CONFIG['github']['enabled'] and self.is_authenticated() and not worker_is_running:
            self.worker = asyncio.create_task(self._run())

    async def trigger(self, delay: int | None = None):
        if not CONFIG['github']['enabled']:
            self.status.update(state='disabled', pending=False)
            return self.status
        if not self.is_authenticated():
            self.status.update(state='unauthenticated', pending=False)
            return self.status

        self.start()
        self.status.update(state='queued', pending=True, last_error=None)
        await self.queue.put(delay if delay is not None else 10)
        return self.status

    async def _run(self) -> None:
        while True:
            delay = await self.queue.get()
            try:
                if delay:
                    await asyncio.sleep(min(max(delay, 0), 300))
                while True:
                    try:
                        delay = self.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    else:
                        self.queue.task_done()
                        if delay:
                            await asyncio.sleep(min(max(delay, 0), 300))
                await self._sync_once()
            finally:
                self.queue.task_done()

    async def _sync_once(self) -> None:
        self.status.update(state='syncing', pending=True, last_error=None)
        try:
            await asyncio.to_thread(self._publish_snapshot)
        except Exception as error:
            self.status.update(
                state=(
                    'conflict'
                    if isinstance(error, GitHubAPIError)
                    and error.status_code in {409, 422}
                    else 'error'
                ),
                last_error=self._safe_error_message(error),
                pending=False,
            )
            return

        self.status.update(
            state='synced',
            last_sync=datetime.now(timezone.utc).isoformat(timespec='seconds'),
            last_error=None,
            pending=False,
            retry_count=0,
        )

    @staticmethod
    def _safe_error_message(error: Exception) -> str:
        if isinstance(error, GitHubAPIError):
            if error.status_code == 401:
                return 'A sessão do GitHub expirou. Entre novamente.'
            if error.status_code == 403:
                return 'O GitHub negou o acesso. Verifique as permissões do OAuth App.'
            if error.status_code == 409:
                return 'O repositório mudou durante a sincronização. Tente novamente.'
        return str(error)

    @staticmethod
    def _git_blob_sha(content: bytes) -> str:
        header = f'blob {len(content)}\0'.encode('ascii')
        return hashlib.sha1(header + content).hexdigest()

    @staticmethod
    @repository_operation
    def _local_snapshot() -> dict[str, bytes]:
        snapshot = {}
        REPO.mkdir(parents=True, exist_ok=True)
        for path in REPO.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            if '.git' in path.relative_to(REPO).parts:
                continue
            snapshot[path.relative_to(REPO).as_posix()] = path.read_bytes()
        return snapshot

    def _publish_snapshot(self) -> None:
        token = self._access_token()
        profile = github_api('/user', token=token)
        repository = self._ensure_repository(profile, token)
        owner, repository_name = repository['full_name'].split('/', 1)
        branch = repository['default_branch']
        repository_path = (
            f"/repos/{quote(owner, safe='')}/{quote(repository_name, safe='')}"
        )
        branch_path = quote(branch, safe='/')

        reference = self._get_branch_reference(repository_path, branch_path, token)
        parent_sha = reference['object']['sha']
        parent_commit = github_api(
            f'{repository_path}/git/commits/{quote(parent_sha, safe="")}',
            token=token,
        )
        base_tree_sha = parent_commit['tree']['sha']
        remote_tree = github_api(
            f'{repository_path}/git/trees/{quote(base_tree_sha, safe="")}?recursive=1',
            token=token,
        )
        if remote_tree.get('truncated'):
            raise RuntimeError('O repositório tem arquivos demais para uma sincronização segura.')

        tree_entries = remote_tree.get('tree', [])
        prefix = f'{SYNC_ROOT}/'
        marker_sha = self._git_blob_sha(MARKER_CONTENT)
        marker = next(
            (entry for entry in tree_entries if entry.get('path') == MARKER_PATH),
            None,
        )
        scoped_entries = [
            entry
            for entry in tree_entries
            if entry.get('type') == 'blob' and entry.get('path', '').startswith(prefix)
        ]
        if marker is not None and marker.get('sha') != marker_sha:
            raise RuntimeError(
                'O marcador do repositório não corresponde ao Docs Local. Nenhum arquivo foi alterado.'
            )

        snapshot = self._local_snapshot()
        local_remote_paths = {
            f'{SYNC_ROOT}/{relative_path}': content
            for relative_path, content in snapshot.items()
        }
        local_remote_paths[MARKER_PATH] = MARKER_CONTENT
        remote_by_path = {
            entry['path']: entry
            for entry in scoped_entries
            if entry.get('path')
        }
        if marker is None and scoped_entries:
            self._validate_legacy_managed_tree(
                remote_by_path,
                local_remote_paths,
                marker_sha,
            )

        changes = []

        for remote_path, remote_entry in remote_by_path.items():
            if remote_path not in local_remote_paths:
                changes.append(
                    {
                        'path': remote_path,
                        'mode': remote_entry.get('mode', GITHUB_FILE_MODE),
                        'type': 'blob',
                        'sha': None,
                    }
                )

        for remote_path, content in local_remote_paths.items():
            if remote_path == MARKER_PATH and marker is not None:
                continue
            if self._git_blob_sha(content) == remote_by_path.get(remote_path, {}).get('sha'):
                continue

            blob = github_api(
                f'{repository_path}/git/blobs',
                method='POST',
                token=token,
                data={
                    'content': base64.b64encode(content).decode('ascii'),
                    'encoding': 'base64',
                },
            )
            changes.append(
                {
                    'path': remote_path,
                    'mode': GITHUB_FILE_MODE,
                    'type': 'blob',
                    'sha': blob['sha'],
                }
            )

        if not changes:
            return

        new_tree = github_api(
            f'{repository_path}/git/trees',
            method='POST',
            token=token,
            data={'base_tree': base_tree_sha, 'tree': changes},
        )
        new_commit = github_api(
            f'{repository_path}/git/commits',
            method='POST',
            token=token,
            data={
                'message': f'docs: sincronização local {time.strftime("%Y-%m-%d %H:%M")}',
                'tree': new_tree['sha'],
                'parents': [parent_sha],
            },
        )
        github_api(
            f'{repository_path}/git/refs/heads/{branch_path}',
            method='PATCH',
            token=token,
            data={'sha': new_commit['sha'], 'force': False},
        )

    @classmethod
    def _validate_legacy_managed_tree(
        cls,
        remote_by_path: dict,
        local_remote_paths: dict[str, bytes],
        marker_sha: str,
    ) -> None:
        legacy_marker_path = f'{SYNC_ROOT}/{MARKER_PATH}'
        legacy_marker = remote_by_path.get(legacy_marker_path)
        expected_files = {
            path: content
            for path, content in local_remote_paths.items()
            if path != MARKER_PATH
        }
        existing_files = {
            path: entry
            for path, entry in remote_by_path.items()
            if path != legacy_marker_path
        }
        matches_local_snapshot = (
            existing_files.keys() == expected_files.keys()
            and all(
                cls._git_blob_sha(content) == existing_files[path].get('sha')
                for path, content in expected_files.items()
            )
        )

        if (
            legacy_marker is None
            or legacy_marker.get('sha') != marker_sha
            or not matches_local_snapshot
        ):
            raise RuntimeError(
                'Já existem arquivos em docs-local-backup/data sem um marcador válido. O app não vai sobrescrever esse backup.'
            )

    @staticmethod
    def _get_branch_reference(repository_path: str, branch: str, token: str) -> dict:
        for attempt in range(4):
            try:
                return github_api(
                    f'{repository_path}/git/ref/heads/{branch}',
                    token=token,
                )
            except GitHubAPIError as error:
                if error.status_code != 409 or attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        raise GitHubAPIError(404, 'O repositório ainda não tem uma branch inicializada.')

    async def status_details(self) -> dict:
        return {
            **self.status,
            'authenticated': self.is_authenticated(),
            'has_local_changes': bool(self.status.get('pending')),
            'git_error': None,
        }

    def history(self) -> list[dict]:
        return self._read_commits()

    def document_history(self, project_id: str, relative_path: str) -> list[dict]:
        path = f'{SYNC_ROOT}/projetos/{project_id}/{relative_path}'
        return self._read_commits(path=path)

    def _read_commits(self, *, path: str | None = None) -> list[dict]:
        if not self.is_authenticated():
            return []
        try:
            token = self._access_token()
            profile = github_api('/user', token=token)
            repository = self._ensure_repository(profile, token)
            owner, repository_name = repository['full_name'].split('/', 1)
            query = {'per_page': 12}
            if path:
                query['path'] = path
            commits = github_api(
                f"/repos/{quote(owner, safe='')}/{quote(repository_name, safe='')}/commits?{urlencode(query)}",
                token=token,
            )
            if not isinstance(commits, list):
                return []
            return [
                {
                    'commit': item.get('sha', '')[:7],
                    'date': (
                        item.get('commit', {})
                        .get('committer', {})
                        .get('date', '')
                    ),
                    'message': item.get('commit', {}).get('message', '').splitlines()[0],
                }
                for item in commits
            ]
        except (GitHubAPIError, RuntimeError, KeyError, TypeError):
            return []

sync_manager = GitHubSync()
