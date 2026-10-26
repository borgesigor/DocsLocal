"""GitHub OAuth, repository setup, and REST-based documentation sync."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import quote, urlencode

from app.core.config import CONFIG, REPO, STATE
from app.core.exceptions import AppError
from app.services.github_client import GitHubAPIError, github_api, oauth_request
from app.services.secret_store import secret_store
from app.services.backup_sync import (
    BackupState, BackupSync, local_snapshot, MANAGED_ROOT, SYNC_ROOT, MARKER_PATH, MARKER_CONTENT,
)
from app.services.sync_merge import blob_sha

GITHUB_CLIENT_ID = 'Ov23lik3T7wS1lMsslVi'
GITHUB_VERIFICATION_URI = 'https://github.com/login/device'
GITHUB_FILE_MODE = '100644'


@dataclass
class DeviceAuthorization:
    attempt_id: str
    device_code: str
    expires_at: float
    interval: int
    next_poll_at: float
    polling: bool = False


class GitHubSync:
    """Queue local snapshots and publish them with GitHub's REST Git API."""

    def __init__(self, state_folder: Path | None = None):
        self.state_folder = state_folder
        self._needs_restore = True
        self._cached_profile: dict | None = None
        self._shutdown_requested = threading.Event()
        self.queue: asyncio.Queue[int] = asyncio.Queue(maxsize=1)
        self.worker: asyncio.Task | None = None
        self.status = {
            'state': 'unauthenticated',
            'last_sync': None,
            'last_error': None,
            'pending': False,
            'retry_count': 0,
        }
        self._auth_lock = threading.RLock()
        self._device_attempt: DeviceAuthorization | None = None

    def is_configured(self) -> bool:
        return bool(GITHUB_CLIENT_ID)

    def is_authenticated(self) -> bool:
        return bool(secret_store.get('access_token'))

    def start_device_authorization(self) -> dict:
        with self._auth_lock:
            self._device_attempt = None
            response = self._oauth_request('device/code', {
                'client_id': GITHUB_CLIENT_ID,
                'scope': 'repo read:user',
            })
            self._raise_device_error(response.get('error'))
            device_code = response.get('device_code')
            user_code = response.get('user_code')
            try:
                expires_in = int(response['expires_in'])
                interval = max(5, int(response.get('interval', 5)))
            except (KeyError, TypeError, ValueError):
                raise AppError(502, 'github_device_invalid', 'O GitHub retornou uma autorização inválida.')
            if (
                not isinstance(device_code, str) or not device_code
                or not isinstance(user_code, str) or not user_code
                or response.get('verification_uri') != GITHUB_VERIFICATION_URI
                or not 0 < expires_in <= 3600
                or interval > expires_in
            ):
                raise AppError(502, 'github_device_invalid', 'O GitHub retornou uma autorização inválida.')

            now = time.monotonic()
            self._device_attempt = DeviceAuthorization(
                secrets.token_urlsafe(32), device_code, now + expires_in, interval, now + interval,
            )
            return {
                'attempt_id': self._device_attempt.attempt_id,
                'user_code': user_code,
                'verification_uri': GITHUB_VERIFICATION_URI,
                'expires_in': expires_in,
                'interval': interval,
            }

    def cancel_device_authorization(self, attempt_id: str) -> None:
        with self._auth_lock:
            if self._device_attempt and secrets.compare_digest(self._device_attempt.attempt_id, attempt_id):
                self._device_attempt = None

    def poll_device_authorization(self, attempt_id: str) -> dict:
        with self._auth_lock:
            attempt = self._device_attempt
            if attempt is None or not secrets.compare_digest(attempt.attempt_id, attempt_id):
                raise AppError(400, 'invalid_device_attempt', 'Inicie novamente o login com GitHub.')
            now = time.monotonic()
            if now >= attempt.expires_at:
                self._device_attempt = None
                self._raise_device_error('expired_token')
            if attempt.polling:
                return {'status': 'pending', 'retry_after': attempt.interval}
            if now < attempt.next_poll_at:
                return {'status': 'pending', 'retry_after': max(1, math.ceil(attempt.next_poll_at - now))}

            attempt.next_poll_at = now + attempt.interval
            attempt.polling = True

        try:
            response = self._oauth_request('access_token', {
                'client_id': GITHUB_CLIENT_ID,
                'device_code': attempt.device_code,
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
            })
        except Exception:
            with self._auth_lock:
                attempt.polling = False
            raise

        with self._auth_lock:
            self._require_current_attempt(attempt)
            error = response.get('error')
            if error in {'authorization_pending', 'slow_down'}:
                attempt.polling = False
                if error == 'slow_down':
                    attempt.interval += 5
                attempt.next_poll_at = time.monotonic() + attempt.interval
                return {'status': 'pending', 'retry_after': attempt.interval}

            if error:
                self._device_attempt = None
                self._raise_device_error(error)

        try:
            profile = self._authorized_profile(response)
        except Exception:
            self.cancel_device_authorization(attempt_id)
            raise

        with self._auth_lock:
            self._require_current_attempt(attempt)
            self._device_attempt = None
            self._connect_account(response, profile)
            return {'status': 'authenticated'}

    def _require_current_attempt(self, attempt: DeviceAuthorization) -> None:
        if self._device_attempt is not attempt:
            raise AppError(400, 'invalid_device_attempt', 'Inicie novamente o login com GitHub.')

    @staticmethod
    def _oauth_request(path: str, values: dict[str, str]) -> dict:
        try:
            return oauth_request(path, values)
        except GitHubAPIError as error:
            if error.code:
                return {'error': error.code}
            raise

    @staticmethod
    def _raise_device_error(error: str | None) -> None:
        if not error:
            return
        messages = {
            'device_flow_disabled': (
                'github_device_disabled',
                'O responsável pelo Docs Local precisa ativar Enable Device Flow no OAuth App do GitHub.',
            ),
            'expired_token': ('github_device_expired', 'O código expirou. Inicie novamente o login com GitHub.'),
            'access_denied': ('github_authorization_denied', 'O acesso ao GitHub foi cancelado.'),
            'incorrect_client_credentials': ('github_app_invalid', 'O GitHub não reconheceu o aplicativo Docs Local.'),
        }
        code, message = messages.get(error, ('github_device_failed', 'Não foi possível autorizar o GitHub. Tente novamente.'))
        raise AppError(400, code, message)

    @staticmethod
    def _authorized_profile(token_response: dict) -> dict:
        access_token = token_response.get('access_token')
        if not isinstance(access_token, str) or not access_token:
            raise AppError(502, 'github_token_missing', 'O GitHub não retornou um token de acesso.')
        profile = github_api('/user', token=access_token)
        if not profile.get('login'):
            raise AppError(502, 'github_profile_missing', 'Não foi possível carregar a conta do GitHub.')
        return profile

    def _connect_account(self, token_response: dict, profile: dict) -> None:
        access_token = token_response['access_token']
        self._cached_profile = profile
        secret_store.write(**self._token_storage_values(token_response))
        try:
            repository = self._ensure_repository(profile, access_token)
            repo_error = None
        except (GitHubAPIError, RuntimeError) as setup_error:
            repository = None
            repo_error = self._safe_error_message(setup_error)
        self._needs_restore = True
        self._store().save_session(self._public_profile(profile), repository)
        self.status.update(state='idle' if repo_error is None else 'error', pending=False, last_error=repo_error)

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
        with self._auth_lock:
            self._device_attempt = None
            self._clear_session()

    def _clear_session(self) -> None:
        self._cached_profile = None
        self._needs_restore = True
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

    def _store(self) -> BackupState:
        return BackupState(self.state_folder or STATE, REPO)

    async def authentication_status(self) -> dict:
        authenticated = self.is_authenticated()
        session = self._store().session() if authenticated else {}
        return {
            'configured': self.is_configured(),
            'authenticated': authenticated,
            'user': session.get('profile'),
            'repository': session.get('repository'),
            'repository_error': self.status.get('last_error') if authenticated else None,
        }

    def _profile(self) -> dict:
        if self._cached_profile is None:
            self._cached_profile = github_api('/user', token=self._access_token())
        return self._cached_profile

    @staticmethod
    def _public_profile(profile: dict) -> dict:
        return {
            'id': profile.get('id'),
            'login': profile.get('login', ''),
            'name': profile.get('name'),
            'avatar_url': profile.get('avatar_url'),
            'html_url': profile.get('html_url'),
        }

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
                    'client_id': GITHUB_CLIENT_ID,
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
            'id': repository.get('id'),
            'name': repository.get('name', repository_name),
            'full_name': repository.get('full_name', f'{owner}/{repository_name}'),
            'html_url': repository.get('html_url'),
            'default_branch': repository.get('default_branch') or 'main',
        }

    def start(self) -> None:
        worker_is_running = self.worker is not None and not self.worker.done()
        if CONFIG['github']['enabled'] and self.is_authenticated() and not worker_is_running:
            self.worker = asyncio.create_task(self._run())

    def _pending_paths(self) -> list[str]:
        store = self._store()
        pending = store.pending_paths(local_snapshot(REPO))
        store.record_pending(pending)
        self.status.update(pending=bool(pending), pending_count=len(pending))
        return pending

    async def trigger(self, delay: int | None = None):
        pending = self._pending_paths()
        if self._shutdown_requested.is_set():
            return self.status
        if not CONFIG['github']['enabled']:
            self.status.update(state='disabled')
            return self.status
        if not self.is_authenticated():
            self.status.update(state='unauthenticated')
            return self.status
        if not pending and not self._needs_restore:
            self.status.update(state='synced', last_error=None)
            return self.status

        self.start()
        self.status.update(state='queued', last_error=None)
        if self.queue.empty():
            self.queue.put_nowait(delay if delay is not None else CONFIG['git']['sync_debounce_seconds'])
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
        if not self._pending_paths() and not self._needs_restore:
            self.status.update(state='synced', last_error=None)
            return
        self.status.update(state='syncing', last_error=None)
        try:
            await asyncio.to_thread(self._publish_snapshot)
        except Exception as error:
            self.status.update(
                state='conflict' if isinstance(error, GitHubAPIError) and error.status_code in {409, 422} else 'error',
                last_error=self._safe_error_message(error),
                retry_count=self.status.get('retry_count', 0) + 1,
            )
            return

        pending = self._pending_paths()
        self.status.update(
            state='queued' if pending else 'synced',
            last_sync=datetime.now(timezone.utc).isoformat(timespec='seconds'),
            last_error=None,
            retry_count=0,
        )
        if pending and self.queue.empty():
            self.queue.put_nowait(0)

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

    _git_blob_sha = staticmethod(blob_sha)

    @staticmethod
    def _local_snapshot() -> dict[str, bytes]:
        return local_snapshot(REPO)

    def _publish_snapshot(self) -> None:
        token = self._access_token()
        profile = self._profile()
        repository = self._ensure_repository(profile, token)
        self._store().save_session(self._public_profile(profile), repository)
        def transfer(*args, **kwargs):
            if self._shutdown_requested.is_set():
                raise RuntimeError('Atualização em andamento. A fila local será retomada ao reiniciar.')
            return github_api(*args, **kwargs)

        result = BackupSync(REPO, self._store(), transfer, self._shutdown_requested.is_set).synchronize(repository, token, self._get_branch_reference)
        self._needs_restore = False
        self.status['conflicts'] = result.conflicts
        if result.restored:
            self.status['workspace_version'] = secrets.token_hex(12)

    def prepare_shutdown(self) -> None:
        self._shutdown_requested.set()
        self._pending_paths()

    def resume(self) -> None:
        self._shutdown_requested.clear()

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
        from app.core.system_projects import SYSTEM_PROJECT_IDS
        if project_id in SYSTEM_PROJECT_IDS:
            return []
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
