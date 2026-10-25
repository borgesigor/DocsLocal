from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from app.services.update_service import UpdateManager
from app.services import updater


class UpdateManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = UpdateManager()
        self.release = {'version': 'v2.0.0', 'name': 'Docs Local 2', 'url': 'unused', 'checksum_url': 'unused'}

    def test_status_polling_never_queries_github(self):
        with patch.object(updater, 'check_latest') as check:
            for _ in range(20):
                self.manager.status()
        check.assert_not_called()

    def test_new_release_notifies_once_and_automatic_checks_are_throttled(self):
        self.manager.notify_available = Mock()
        with patch.object(updater, 'check_latest', return_value=self.release) as check:
            self.manager.check()
            self.manager.check()
            self.manager.check(manual=True)
        self.assertEqual(check.call_count, 2)
        self.manager.notify_available.assert_called_once_with()
        self.assertEqual(self.manager.status()['available_version'], 'v2.0.0')

    def test_defer_does_not_download_or_close_the_application(self):
        self.manager.release = self.release
        with patch.object(updater, 'download_update') as download:
            self.manager.defer()
        download.assert_not_called()
        self.assertGreater(self.manager.status()['deferred_until'], 0)

    def test_failed_integrity_verification_never_closes_application(self):
        self.manager.shutdown = Mock()
        with (
            patch.object(updater, 'download_update', side_effect=updater.UpdateError('Checksum inválido')),
            patch.object(updater, 'launch_update_helper') as helper,
        ):
            self.manager._install(self.release)
        helper.assert_not_called()
        self.manager.shutdown.assert_not_called()
        self.assertEqual(self.manager.status()['state'], 'error')

    def test_installation_downloads_then_preserves_queue_launches_helper_and_shuts_down(self):
        actions = []
        self.manager.prepare_shutdown = lambda: actions.append('persist_queue')
        self.manager.shutdown = lambda: actions.append('shutdown')
        with (
            patch.object(updater, 'download_update', side_effect=lambda release: actions.append('verified_download') or Path('update.exe')),
            patch.object(updater, 'launch_update_helper', side_effect=lambda *args: actions.append('helper')),
        ):
            self.manager._install(self.release)
        self.assertEqual(actions, ['verified_download', 'persist_queue', 'helper', 'shutdown'])
        self.assertEqual(self.manager.status()['state'], 'restarting')

    def test_multiple_tabs_cannot_start_duplicate_installations(self):
        self.manager.release = self.release
        self.manager.shutdown = Mock()
        with patch.object(sys, 'frozen', True, create=True), patch('app.services.update_service.threading.Thread') as thread:
            self.manager.start_install()
            self.manager.start_install()
        self.assertEqual(thread.call_count, 1)

    def test_source_checkout_cannot_replace_python_interpreter(self):
        self.manager.release = self.release
        self.manager.shutdown = Mock()
        with patch.object(sys, 'frozen', False, create=True):
            with self.assertRaises(updater.UpdateError):
                self.manager.start_install()

    def test_unsaved_document_in_another_tab_blocks_installation(self):
        self.manager.release = self.release
        self.manager.shutdown = Mock()
        self.manager.hold('other-tab', True)
        with patch.object(sys, 'frozen', True, create=True):
            with self.assertRaisesRegex(updater.UpdateError, 'não salvo'):
                self.manager.start_install()
        self.manager.hold('other-tab', False)
        with patch.object(sys, 'frozen', True, create=True), patch('app.services.update_service.threading.Thread'):
            self.manager.start_install()
        self.assertEqual(self.manager.status()['state'], 'downloading')

    def test_edit_started_during_download_prevents_shutdown(self):
        self.manager.shutdown = Mock()
        self.manager.hold('other-tab', True)
        with patch.object(updater, 'download_update', return_value=Path('update.exe')), patch.object(updater, 'launch_update_helper') as helper:
            self.manager._install(self.release)
        helper.assert_not_called()
        self.manager.shutdown.assert_not_called()
        self.assertEqual(self.manager.status()['state'], 'error')
