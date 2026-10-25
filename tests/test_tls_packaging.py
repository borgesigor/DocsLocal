from pathlib import Path
import shutil
import ssl
import tempfile
import unittest
from unittest.mock import patch


class TlsPackagingRegressionTests(unittest.TestCase):
    def test_adjacent_tls_resource_is_required_and_preserves_certificate_verification(self):
        resource = Path(ssl.__file__).with_name('codex-rejected-cas.pem')
        if not resource.is_file():
            self.skipTest('This Python distribution does not use the additional TLS resource.')
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            extracted = Path(folder)
            with patch.object(ssl, '__file__', str(extracted / 'ssl.pyc')):
                with self.assertRaises(FileNotFoundError) as missing:
                    ssl.create_default_context()
                self.assertEqual(missing.exception.errno, 2)
                shutil.copyfile(resource, extracted / resource.name)
                context = ssl.create_default_context()
                self.assertTrue(context.check_hostname)
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
