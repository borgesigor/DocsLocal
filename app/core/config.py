from pathlib import Path
import os
import sys
import tomllib

FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[2]
DATA = (
    Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'DocsLocal'
    if FROZEN
    else ROOT / 'data'
)

DEFAULTS = {
    'server': {
        'host': '127.0.0.1',
        'port': 8765,
        'open_browser_on_start': False,
    },
    'storage': {'repository_path': './data/repository'},
    'git': {
        'enabled': True,
        'remote': 'origin',
        'branch': 'main',
        'sync_debounce_seconds': 10,
        'retry_enabled': True,
        'periodic_check_seconds': 60,
    },
    'github': {
        'enabled': True,
        'client_id': '',
        'repository_name': 'docs-local-backup',
    },
    'editor': {'autosave_enabled': True, 'autosave_debounce_ms': 1000},
    'search': {'enabled': True},
    'logging': {'level': 'INFO'},
}

DEFAULT_CONFIG = '''\
[server]
host = "127.0.0.1"
port = 8765
open_browser_on_start = false

[storage]
repository_path = "./data/repository"

[git]
enabled = true
remote = "origin"
branch = "main"
sync_debounce_seconds = 10
retry_enabled = true
periodic_check_seconds = 60

[github]
enabled = true
client_id = ""
repository_name = "docs-local-backup"

[editor]
autosave_enabled = true
autosave_debounce_ms = 1000

[search]
enabled = true

[logging]
level = "INFO"
'''

def load_config():
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / 'config.toml'
    if not path.exists():
        path.write_text(DEFAULT_CONFIG, encoding='utf-8')
    with path.open('rb') as f:
        incoming = tomllib.load(f)
    cfg = {
        section: {**defaults, **incoming.get(section, {})}
        for section, defaults in DEFAULTS.items()
    }
    repo = Path(cfg['storage']['repository_path'])
    if not repo.is_absolute():
        if FROZEN:
            if repo.parts and repo.parts[0] == 'data':
                repo = Path(*repo.parts[1:])
            repo = DATA / repo
        else:
            repo = ROOT / repo
    cfg['storage']['repository_path'] = repo.resolve()
    if cfg['server']['host'] not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('Por segurança, o host deve ser loopback (127.0.0.1).')
    port = int(cfg['server']['port'])
    if not 1 <= port <= 65535:
        raise ValueError('Porta inválida.')
    return cfg


CONFIG = load_config()
REPO = Path(CONFIG['storage']['repository_path'])
PROJECTS = REPO / 'projetos'
STATE = DATA / 'state'
