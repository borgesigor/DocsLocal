from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if len(sys.argv) == 3 and sys.argv[1] in {'--check-tls', '--check-update-network'}:
    import json
    import ssl
    import traceback
    from app.version import VERSION

    report = {'version': VERSION, 'tls_ready': False, 'network_checked': False}
    try:
        context = ssl.create_default_context()
        report['tls_ready'] = context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        if sys.argv[1] == '--check-update-network':
            from app.services import updater
            release = updater.check_latest()
            report['network_checked'] = True
            report['available_version'] = release['version'] if release else None
    except Exception:
        report['error'] = traceback.format_exc()
    Path(sys.argv[2]).write_text(json.dumps(report, indent=2), encoding='utf-8')
    success = report['tls_ready'] and (sys.argv[1] == '--check-tls' or report['network_checked'])
    raise SystemExit(0 if success else 1)
elif len(sys.argv) == 3 and sys.argv[1] == '--check-installation':
    import json
    from app.core.config import CONFIG, DATA, REPO, STATE
    from app.main import app, BUILT_FILES
    from app.services.project_service import list_projects
    from app.services.secret_store import secret_store
    from app.services.github_service import GITHUB_CLIENT_ID
    from app.version import VERSION

    report = {
        'version': VERSION,
        'data_path': str(DATA),
        'repository_path': str(REPO),
        'project_count': len(list_projects()),
        'oauth_client_id': GITHUB_CLIENT_ID,
        'credential_count': len(secret_store.read_all()),
        'frontend_present': (BUILT_FILES / 'index.html').is_file(),
        'route_count': len(app.openapi()['paths']),
    }
    Path(sys.argv[2]).write_text(json.dumps(report, indent=2), encoding='utf-8')
    raise SystemExit(0 if report['frontend_present'] and report['route_count'] else 1)
else:
    from app.tray import main
    main()
