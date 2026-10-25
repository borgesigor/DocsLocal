"""Read-only repository diagnostics, shared with the integrity API."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECTS
from app.services.integrity_service import check_integrity


if __name__ == '__main__':
    result = check_integrity(PROJECTS)
    for issue in result['issues']:
        print(f"{issue['project_id']}/{issue['path']}: {issue['issue']}")
    if not result['ok']:
        raise SystemExit(1)
    print(f"Integridade OK: {result['projects']} projeto(s).")
