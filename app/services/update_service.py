"""Coordinate release checks, the update modal, and a graceful restart."""

import asyncio
import os
from pathlib import Path
import sys
import threading
import time

from app.services import updater
from app.services.storage import REPOSITORY_LOCK
from app.version import VERSION

CHECK_INTERVAL = 6 * 60 * 60


class UpdateManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._checking = False
        self._last_check = None
        self.release: dict | None = None
        self.state = 'idle'
        self.error: str | None = None
        self.deferred_until = 0.0
        self.shutdown = None
        self.prepare_shutdown = None
        self.resume = None
        self.notify_available = None
        self._editing_clients: dict[str, float] = {}

    def hold(self, client_id: str, dirty: bool) -> None:
        with self._lock:
            if dirty:
                self._editing_clients[client_id] = time.monotonic() + 30
            else:
                self._editing_clients.pop(client_id, None)

    def _has_unsaved_documents(self) -> bool:
        now = time.monotonic()
        self._editing_clients = {client: expires for client, expires in self._editing_clients.items() if expires > now}
        return bool(self._editing_clients)

    def status(self) -> dict:
        with self._lock:
            return {
                'current_version': VERSION,
                'available_version': self.release['version'] if self.release else None,
                'release_name': self.release['name'] if self.release else None,
                'state': self.state,
                'error': self.error,
                'supported': bool(getattr(sys, 'frozen', False) and self.shutdown),
                'deferred_until': self.deferred_until,
            }

    def check(self, *, manual=False) -> dict:
        with self._lock:
            if self._checking or self.state in {'downloading', 'restarting'}:
                return self.status()
            if not manual and self._last_check is not None and time.monotonic() - self._last_check < CHECK_INTERVAL:
                return self.status()
            self._checking = True
        notify = False
        try:
            release = updater.check_latest()
            with self._lock:
                previous = self.release['version'] if self.release else None
                self.release = release
                self.state = 'available' if release else 'idle'
                self.error = None
                notify = release is not None and release['version'] != previous
                if notify:
                    self.deferred_until = 0
        except Exception as error:
            with self._lock:
                self.error = str(error)
        finally:
            with self._lock:
                self._checking = False
                self._last_check = time.monotonic()
        if notify and self.notify_available:
            self.notify_available()
        return self.status()

    def defer(self) -> dict:
        with self._lock:
            if self.state not in {'downloading', 'restarting'}:
                self.deferred_until = time.time() + 3600
        return self.status()

    def start_install(self) -> dict:
        with self._lock:
            if not self.status()['supported']:
                raise updater.UpdateError('A atualização automática requer o executável Windows instalado.')
            if self.state in {'downloading', 'restarting'}:
                return self.status()
            if self.release is None:
                raise updater.UpdateError('Não há uma atualização disponível.')
            if self._has_unsaved_documents():
                raise updater.UpdateError('Há um documento não salvo em outra janela. Salve-o antes de atualizar.')
            self.state = 'downloading'
            self.error = None
            release = dict(self.release)
            threading.Thread(target=self._install, args=(release,), name='docs-local-install-update', daemon=True).start()
        return self.status()

    def _install(self, release: dict) -> None:
        prepared = False
        try:
            staged = updater.download_update(release)
            with REPOSITORY_LOCK:
                with self._lock:
                    if self._has_unsaved_documents():
                        raise updater.UpdateError('A atualização foi pausada porque há um documento não salvo em outra janela.')
                if self.prepare_shutdown:
                    self.prepare_shutdown()
                    prepared = True
                updater.launch_update_helper(staged, Path(sys.executable), os.getpid())
                with self._lock:
                    self.state = 'restarting'
                self.shutdown()
        except Exception as error:
            if prepared and self.resume:
                self.resume()
            with self._lock:
                self.state = 'error'
                self.error = str(error)

    async def watch(self) -> None:
        if not getattr(sys, 'frozen', False):
            return
        await asyncio.sleep(60)
        while True:
            await asyncio.to_thread(self.check)
            await asyncio.sleep(CHECK_INTERVAL)


update_manager = UpdateManager()
