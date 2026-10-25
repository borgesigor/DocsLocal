"""Check GitHub Releases and safely replace the installed Windows executable."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from app.version import GITHUB_REPOSITORY, VERSION

RELEASE_URL = f'https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest'
ASSET_NAME = 'DocsLocal.exe'
CHECKSUM_NAME = f'{ASSET_NAME}.sha256'
MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024


class UpdateError(RuntimeError):
    pass


def _request(url: str, *, accept: str = 'application/vnd.github+json'):
    request = Request(
        url,
        headers={
            'Accept': accept,
            'User-Agent': 'DocsLocal-Updater',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    return urlopen(request, timeout=20)


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r'v?(\d+(?:\.\d+){1,3})', value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split('.'))


def check_latest() -> dict | None:
    """Return latest release metadata only when its numeric version is newer."""
    with _request(RELEASE_URL) as response:
        release = json.loads(response.read(1024 * 1024).decode('utf-8'))

    tag = release.get('tag_name', '')
    latest_version = _version_tuple(tag)
    current_version = _version_tuple(VERSION)
    if release.get('draft') or release.get('prerelease') or not latest_version:
        return None
    if current_version is None or latest_version <= current_version:
        return None

    assets = {asset.get('name'): asset for asset in release.get('assets', [])}
    executable = assets.get(ASSET_NAME)
    checksum = assets.get(CHECKSUM_NAME)
    if not executable or not checksum:
        raise UpdateError('A release não contém o executável e o checksum esperados.')
    return {
        'version': tag,
        'name': release.get('name') or tag,
        'url': executable.get('browser_download_url'),
        'checksum_url': checksum.get('browser_download_url'),
    }


def download_update(release: dict) -> Path:
    if not getattr(sys, 'frozen', False):
        raise UpdateError('A instalação automática está disponível apenas no executável Windows.')
    if not release.get('url') or not release.get('checksum_url'):
        raise UpdateError('A release não contém links válidos para os arquivos.')

    update_dir = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DocsLocal' / 'updates'
    update_dir.mkdir(parents=True, exist_ok=True)
    staged = update_dir / f'DocsLocal-{release["version"]}.exe'
    digest = hashlib.sha256()
    total = 0
    temporary = staged.with_suffix('.download')
    try:
        with _request(release['url'], accept='application/octet-stream') as response, temporary.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise UpdateError('O arquivo de atualização excede o limite de tamanho.')
                digest.update(chunk)
                output.write(chunk)

        with _request(release['checksum_url'], accept='application/octet-stream') as response:
            checksum_text = response.read(4096).decode('ascii', errors='strict')
        expected = checksum_text.strip().split()[0].lower()
        if not re.fullmatch(r'[0-9a-f]{64}', expected) or digest.hexdigest() != expected:
            raise UpdateError('A verificação SHA-256 da atualização falhou.')
        os.replace(temporary, staged)
        return staged
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def launch_update_helper(staged_executable: Path, target_executable: Path, process_id: int) -> None:
    if os.name != 'nt':
        raise UpdateError('A atualização automática está disponível apenas no Windows.')
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0x00000008) | getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    subprocess.Popen(
        [str(staged_executable), '--apply-update', str(process_id), str(target_executable)],
        close_fds=True,
        creationflags=flags,
        cwd=str(staged_executable.parent),
    )


def apply_update_after_exit(process_id: int, target_executable: Path) -> int:
    """Helper mode: wait for the old app, atomically replace it, then relaunch."""
    if os.name != 'nt':
        return 2
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]

    process = open_process(0x00100000, False, process_id)  # SYNCHRONIZE
    if process:
        try:
            if wait_for_single_object(process, 60_000) != 0:
                return 3
        finally:
            close_handle(process)

    source = Path(sys.executable).resolve()
    target = target_executable.resolve()
    replacement = target.with_suffix(target.suffix + '.new')
    try:
        for attempt in range(20):
            try:
                replacement.write_bytes(source.read_bytes())
                os.replace(replacement, target)
                subprocess.Popen([str(target), '--updated'], close_fds=True, cwd=str(target.parent))
                return 0
            except OSError:
                replacement.unlink(missing_ok=True)
                time.sleep(0.5 + attempt * 0.25)
    except OSError:
        replacement.unlink(missing_ok=True)
    return 4
