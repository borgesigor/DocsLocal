import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from app.services import local_url_service


class LocalUrlTests(unittest.TestCase):
    def test_alias_requires_a_healthy_docs_local_response(self):
        for health, expected in (({'service': 'docs-local', 'status': 'ok'}, True),
                                 ({'service': 'other', 'status': 'ok'}, False), ([], False)):
            opener = Mock()
            opener.open.return_value = io.BytesIO(json.dumps(health).encode())
            with patch.object(local_url_service.urllib.request, 'build_opener', return_value=opener):
                self.assertEqual(local_url_service.is_available(), expected)

    def test_unavailable_alias_allows_the_numeric_url_fallback(self):
        with patch.object(local_url_service.urllib.request, 'build_opener', side_effect=OSError):
            self.assertFalse(local_url_service.is_available())

    def test_configuration_requests_elevation_for_the_bundled_script(self):
        with patch.object(local_url_service.subprocess, 'run') as run:
            local_url_service.configure('127.0.0.1', 8765)
        command = run.call_args.args[0][-1]
        self.assertIn('configure-local-url.ps1', command)
        self.assertIn('-Verb RunAs -WindowStyle Hidden', command)
        self.assertIn('-ServerHost 127.0.0.1 -Port 8765', command)
        self.assertTrue(run.call_args.kwargs['check'])

    def test_configuration_failure_is_reported_to_the_tray(self):
        with patch.object(local_url_service.subprocess, 'run',
                          side_effect=subprocess.CalledProcessError(1, 'powershell')):
            with self.assertRaises(subprocess.CalledProcessError):
                local_url_service.configure('127.0.0.1', 8765)

    def test_non_loopback_addresses_are_rejected_before_running_commands(self):
        with patch.object(local_url_service.subprocess, 'run') as run:
            for host, port in (('0.0.0.0', 8765), ('127.0.0.1', 0), ('127.0.0.1', 65536)):
                with self.assertRaises(ValueError):
                    local_url_service.configure(host, port)
            run.assert_not_called()
