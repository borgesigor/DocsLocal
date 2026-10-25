import asyncio
import json
import re
import subprocess
import time
from pathlib import Path

from app.core.config import CONFIG, REPO, STATE
from app.services.storage import atomic_write

STATUS_FILE = STATE / 'sync.json'
REMOTE_NAME = re.compile(r'^[A-Za-z0-9._-]+$')
BRANCH_NAME = re.compile(r'^[A-Za-z0-9._/-]+$')
GIT_PROCESS_CREATION_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class GitSync:
    """Serialize local Git commits and pushes for the documentation repository."""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.worker = None
        self.lock = asyncio.Lock()
        self.status = {
            'state': 'disabled' if not CONFIG['git']['enabled'] else 'idle',
            'last_sync': None,
            'last_error': None,
            'pending': False,
            'retry_count': 0,
        }
        self._load_status()

    def _load_status(self):
        try:
            saved_status = json.loads(STATUS_FILE.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return
        self.status.update(saved_status)

    def _save_status(self):
        STATE.mkdir(parents=True, exist_ok=True)
        serialized_status = json.dumps(self.status, ensure_ascii=False, indent=2)
        atomic_write(STATUS_FILE, serialized_status)

    def start(self):
        worker_is_running = self.worker is not None and not self.worker.done()
        if CONFIG['git']['enabled'] and not worker_is_running:
            self.worker = asyncio.create_task(self._run())

    async def trigger(self, delay: int | None = None):
        if not CONFIG['git']['enabled']:
            return self.status

        self.start()
        self.status['pending'] = True
        self.status['state'] = 'queued'
        self._save_status()
        debounce = delay if delay is not None else CONFIG['git']['sync_debounce_seconds']
        await self.queue.put(debounce)
        return self.status

    async def _run_git(self, *arguments: str):
        process = await asyncio.create_subprocess_exec(
            'git',
            *arguments,
            cwd=REPO,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=GIT_PROCESS_CREATION_FLAGS,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except asyncio.CancelledError:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            await process.wait()
            raise
        except asyncio.TimeoutError as error:
            process.kill()
            await process.wait()
            raise TimeoutError('A operação Git excedeu o limite de 60 segundos.') from error

        return (
            process.returncode,
            stdout.decode(errors='replace').strip(),
            stderr.decode(errors='replace').strip(),
        )

    async def _run(self):
        while True:
            debounce = await self.queue.get()
            try:
                debounce = await self._wait_for_quiet_period(debounce)
                async with self.lock:
                    await self._sync_once()
            finally:
                self.queue.task_done()

            if (
                self.status['state'] == 'error'
                and CONFIG['git']['retry_enabled']
                and not self.requires_remote_configuration()
            ):
                await self._retry_after_backoff()
            elif self.status['state'] == 'synced':
                self.status['retry_count'] = 0
                self._save_status()

    async def _wait_for_quiet_period(self, debounce: int):
        delay = min(max(float(debounce), 0), 300)
        while delay:
            await asyncio.sleep(delay)
            try:
                delay = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return 0
            self.queue.task_done()
            delay = min(max(float(delay), 0), 300)
        return 0

    async def _retry_after_backoff(self):
        retry_count = int(self.status.get('retry_count', 0))
        retry_delay = min(300, 10 * 2 ** min(retry_count, 5))
        self.status['retry_count'] = retry_count + 1
        self._save_status()
        await asyncio.sleep(retry_delay)
        await self.queue.put(0)

    async def _sync_once(self):
        self.status.update(state='syncing', last_error=None, pending=True)
        self._save_status()

        try:
            await self._ensure_repository()
            await self._commit_local_changes()
            await self._push_branch()
            self.status.update(
                state='synced',
                last_sync=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                last_error=None,
                pending=False,
            )
        except Exception as error:
            if self.status['state'] != 'conflict':
                self.status['state'] = 'error'
            self.status.update(
                last_error=str(error),
                pending=not self._is_missing_remote_error(str(error)),
            )
        self._save_status()

    @staticmethod
    def _is_missing_remote_error(error: str | None) -> bool:
        normalized_error = (error or '').casefold()
        return 'no such remote' in normalized_error or (
            'remote' in normalized_error and 'not configured' in normalized_error
        )

    def requires_remote_configuration(self) -> bool:
        return self._is_missing_remote_error(self.status.get('last_error'))

    async def _ensure_repository(self):
        REPO.mkdir(parents=True, exist_ok=True)
        if not (REPO / '.git').exists():
            branch = CONFIG['git']['branch']
            return_code, stdout, stderr = await self._run_git('init', '-b', branch)
            if return_code:
                raise RuntimeError(stderr or stdout)

        return_code, _, _ = await self._run_git('config', 'user.name')
        if return_code:
            await self._run_git('config', 'user.name', 'Docs Local')

        return_code, _, _ = await self._run_git('config', 'user.email')
        if return_code:
            await self._run_git('config', 'user.email', 'docs-local@localhost')

    async def _commit_local_changes(self):
        return_code, changes, error = await self._run_git('status', '--porcelain')
        if return_code:
            raise RuntimeError(error or 'Não foi possível consultar o estado do Git.')
        if not changes:
            return

        return_code, stdout, stderr = await self._run_git('add', '-A')
        if return_code:
            raise RuntimeError(stderr or stdout or 'Não foi possível preparar arquivos para commit.')

        commit_message = f"docs: atualizações locais ({time.strftime('%Y-%m-%d %H:%M')})"
        return_code, stdout, stderr = await self._run_git('commit', '-m', commit_message)
        if return_code and 'nothing to commit' not in stderr.casefold():
            raise RuntimeError(stderr or stdout)

    async def _push_branch(self):
        remote = CONFIG['git']['remote']
        branch = CONFIG['git']['branch']
        if not REMOTE_NAME.fullmatch(remote):
            raise RuntimeError('O nome do remoto Git contém caracteres inválidos.')
        if not BRANCH_NAME.fullmatch(branch) or branch.startswith('-') or '..' in branch:
            raise RuntimeError('O nome da branch Git contém caracteres inválidos.')

        return_code, _, error = await self._run_git('remote', 'get-url', remote)
        if return_code:
            raise RuntimeError(f"Remoto Git '{remote}' não configurado. {error}".strip())

        return_code, stdout, stderr = await self._run_git(
            'push',
            remote,
            f'HEAD:{branch}',
        )
        if return_code:
            error_message = stderr or stdout
            if 'rejected' in error_message.casefold() or 'non-fast-forward' in error_message.casefold():
                self.status['state'] = 'conflict'
            raise RuntimeError(error_message)

    async def status_details(self):
        try:
            return_code, changes, error = await self._run_git('status', '--porcelain')
        except OSError as error:
            return {
                **self.status,
                'has_local_changes': False,
                'git_error': str(error),
            }

        return {
            **self.status,
            'has_local_changes': bool(changes) if return_code == 0 else False,
            'git_error': error or None,
        }

    def history(self):
        arguments = ['git', 'log', '-12', '--format=%h%x09%aI%x09%s']
        return self._read_history(arguments)

    def document_history(self, project_id: str, relative_path: str):
        repository_path = f'projetos/{project_id}/{relative_path}'
        arguments = [
            'git',
            'log',
            '--follow',
            '-20',
            '--format=%h%x09%aI%x09%s',
            '--',
            repository_path,
        ]
        return self._read_history(arguments)

    @staticmethod
    def _read_history(arguments: list[str]):
        try:
            result = subprocess.run(
                arguments,
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=GIT_PROCESS_CREATION_FLAGS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []

        entries = []
        for line in result.stdout.splitlines():
            parts = line.split('\t', 2)
            if len(parts) == 3:
                entries.append(
                    {'commit': parts[0], 'date': parts[1], 'message': parts[2]}
                )
        return entries


sync_manager = GitSync()
