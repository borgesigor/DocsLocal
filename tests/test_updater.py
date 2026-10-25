import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.services import updater


def release(version='v1.0.1', **extra):
    return {
        'tag_name': version,
        'assets': [
            {'name': updater.ASSET_NAME, 'browser_download_url': 'https://github.com/example/app/releases/download/v1.0.1/DocsLocal.exe'},
            {'name': updater.CHECKSUM_NAME, 'browser_download_url': 'https://github.com/example/app/releases/download/v1.0.1/DocsLocal.exe.sha256'},
        ],
        **extra,
    }


class UpdaterTests(unittest.TestCase):
    def test_only_newer_stable_release_is_offered(self):
        for payload, offered in (
            (release('v1.0.1'), True),
            (release('v1.0.0'), False),
            (release('v0.9.0'), False),
            (release('v2.0.0', prerelease=True), False),
            (release('v2.0.0', draft=True), False),
        ):
            with self.subTest(payload=payload), patch.object(updater, 'VERSION', '1.0.0'), patch.object(
                updater, '_request', return_value=io.BytesIO(json.dumps(payload).encode())
            ):
                self.assertEqual(updater.check_latest() is not None, offered)

    def test_release_without_binary_and_checksum_is_rejected(self):
        with patch.object(updater, 'VERSION', '1.0.0'), patch.object(updater, '_request', return_value=io.BytesIO(json.dumps(release(assets=[])).encode())):
            with self.assertRaises(updater.UpdateError):
                updater.check_latest()

    def test_download_checks_integrity_and_rejects_corruption(self):
        binary = b'MZ-example-executable'
        checksum = hashlib.sha256(binary).hexdigest().encode() + b'  DocsLocal.exe'
        for expected, accepted in ((checksum, True), (b'0' * 64, False)):
            with (
                self.subTest(accepted=accepted),
                tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder,
                patch.dict(os.environ, {'LOCALAPPDATA': folder}),
                patch.object(sys, 'frozen', True, create=True),
                patch.object(updater, '_request', side_effect=[io.BytesIO(binary), io.BytesIO(expected)]),
            ):
                metadata = {'version': 'v1.0.1', 'url': 'https://example.invalid/app.exe', 'checksum_url': 'https://example.invalid/app.exe.sha256'}
                if accepted:
                    self.assertEqual(updater.download_update(metadata).read_bytes(), binary)
                else:
                    with self.assertRaises(updater.UpdateError):
                        updater.download_update(metadata)
                    self.assertEqual(list(Path(folder).rglob('*.download')), [])
                    self.assertEqual(list(Path(folder).rglob('*.exe')), [])
