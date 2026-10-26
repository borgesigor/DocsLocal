"""Configure the Windows loopback alias without running the app as administrator."""

import json
from pathlib import Path
import subprocess
import urllib.request

LOCAL_URL = 'http://docs.local'


def is_available() -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'{LOCAL_URL}/api/v1/health', timeout=1) as response:
            health = json.load(response)
        return isinstance(health, dict) and health.get('service') == 'docs-local' and health.get('status') == 'ok'
    except (OSError, ValueError):
        return False


def configure(host: str, port: int) -> None:
    if host not in {'127.0.0.1', 'localhost', '::1'} or not 1 <= port <= 65535:
        raise ValueError('Invalid loopback address or port')
    script = Path(__file__).parents[1] / 'static' / 'configure-local-url.ps1'
    # The installed binary can live in a path containing apostrophes.
    script_literal = str(script).replace("'", "''")
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$process = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"{script_literal}\" "
        f"-ServerHost {host} -Port {port}' -Wait -PassThru; exit $process.ExitCode"
    )
    subprocess.run(
        ['powershell.exe', '-NoProfile', '-Command', command],
        check=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
