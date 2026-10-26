import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services.backup_sync import BackupState, BackupSync, MARKER_PATH, MARKER_CONTENT, SYNC_ROOT, local_snapshot
from app.services.github_client import GitHubAPIError
from app.services.github_service import GitHubSync
from app.services import github_service
from app.services.sync_merge import blob_sha

REPOSITORY = {'id': 42, 'full_name': 'octocat/docs-local-backup', 'default_branch': 'main'}
PREFIX = '/repos/octocat/docs-local-backup'


class MemoryGitHub:
    def __init__(self, files):
        self.files = {MARKER_PATH: MARKER_CONTENT, 'README.md': b'Unmanaged', **{f'{SYNC_ROOT}/{path}': value for path, value in files.items()}}
        self.blobs = {blob_sha(value): value for value in self.files.values()}
        self.calls = []
        self.next_files = None
        self.reject_push = False
        self.on_download = lambda: None

    def __call__(self, path, *, method='GET', token=None, data=None):
        self.calls.append((method, path, data))
        if method == 'GET':
            if '/git/ref/heads/' in path:
                return {'object': {'sha': 'head'}}
            if '/git/commits/' in path:
                return {'tree': {'sha': 'tree'}}
            if '/git/trees/' in path:
                return {'tree': [{'path': name, 'type': 'blob', 'mode': '100644', 'sha': blob_sha(content)} for name, content in self.files.items()]}
            if '/git/blobs/' in path:
                self.on_download()
                return {'content': base64.b64encode(self.blobs[path.rsplit('/', 1)[1]]).decode(), 'encoding': 'base64'}
        if method == 'POST' and path.endswith('/git/blobs'):
            content = base64.b64decode(data['content'])
            sha = blob_sha(content)
            self.blobs[sha] = content
            return {'sha': sha}
        if method == 'POST' and path.endswith('/git/trees'):
            self.next_files = dict(self.files)
            for entry in data['tree']:
                if entry['sha'] is None:
                    self.next_files.pop(entry['path'], None)
                else:
                    self.next_files[entry['path']] = self.blobs[entry['sha']]
            return {'sha': 'new-tree'}
        if method == 'POST' and path.endswith('/git/commits'):
            return {'sha': 'new-head'}
        if method == 'PATCH':
            if self.reject_push:
                raise GitHubAPIError(409, 'Head changed')
            self.files = self.next_files
            return {}
        raise AssertionError((method, path))


class BackupSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'repository'
        self.root.mkdir()
        self.state = BackupState(Path(self.temporary.name) / 'state')

    def synchronize(self, api):
        return BackupSync(self.root, self.state, api).synchronize(REPOSITORY, 'token', lambda path, branch, token: api(f'{path}/git/ref/heads/{branch}', token=token))

    def test_installation_restores_existing_backup_without_remote_deletions(self):
        api = MemoryGitHub({'projetos/p/index.md': b'# Existing', 'projetos/p/docs/a.md': b'Important'})
        result = self.synchronize(api)
        self.assertEqual(local_snapshot(self.root), {'projetos/p/index.md': b'# Existing', 'projetos/p/docs/a.md': b'Important'})
        self.assertTrue(result.restored)
        self.assertFalse(any(method != 'GET' for method, _, _ in api.calls))
        self.assertEqual(api.files['README.md'], b'Unmanaged')

    def test_new_repository_receives_local_files_and_only_changed_blobs_are_sent(self):
        api = MemoryGitHub({})
        (self.root / 'a.md').write_bytes(b'New')
        self.synchronize(api)
        self.assertEqual(api.files[f'{SYNC_ROOT}/a.md'], b'New')
        api.calls.clear()
        self.synchronize(api)
        self.assertFalse(any(method != 'GET' for method, _, _ in api.calls))
        self.assertFalse(any('/git/blobs/' in path for _, path, _ in api.calls))

    def test_remote_files_and_pending_local_files_survive_restart(self):
        api = MemoryGitHub({'remote.md': b'Remote'})
        (self.root / 'local.md').write_bytes(b'Local pending')
        self.state.record_pending(['local.md'])
        self.state = BackupState(self.state.folder.parent)
        self.synchronize(api)
        self.assertEqual(local_snapshot(self.root), {'remote.md': b'Remote', 'local.md': b'Local pending'})
        self.assertEqual(api.files[f'{SYNC_ROOT}/local.md'], b'Local pending')
        self.assertEqual(self.state.pending_paths(local_snapshot(self.root), self.state.binding(REPOSITORY)), [])

    def test_remote_change_during_publish_is_retried_without_losing_local_files(self):
        api = MemoryGitHub({'remote.md': b'Remote'})
        (self.root / 'local.md').write_bytes(b'Local')
        api.reject_push = True
        with self.assertRaises(GitHubAPIError):
            self.synchronize(api)
        self.assertEqual((self.root / 'local.md').read_bytes(), b'Local')
        self.assertEqual((self.root / 'remote.md').read_bytes(), b'Remote')
        api.reject_push = False
        self.synchronize(api)
        self.assertEqual(api.files[f'{SYNC_ROOT}/local.md'], b'Local')

    def test_edit_during_restore_is_kept_in_persistent_outbox(self):
        api = MemoryGitHub({'a.md': b'Remote edit'})
        (self.root / 'a.md').write_bytes(b'Old')
        self.state.save_baseline(self.state.binding(REPOSITORY), {'a.md': b'Old'})
        api.on_download = lambda: (self.root / 'a.md').write_bytes(b'Edit during sync')
        self.synchronize(api)
        self.assertEqual((self.root / 'a.md').read_bytes(), b'Edit during sync')
        outbox = json.loads((self.state.folder / 'outbox.json').read_text())
        self.assertEqual(outbox['paths'], ['a.md'])

    def test_only_known_local_deletions_are_removed_from_remote(self):
        api = MemoryGitHub({'removed.md': b'Known', 'new-remote.md': b'Remote new'})
        self.state.save_baseline(self.state.binding(REPOSITORY), {'removed.md': b'Known'})
        self.synchronize(api)
        self.assertNotIn(f'{SYNC_ROOT}/removed.md', api.files)
        self.assertEqual(api.files[f'{SYNC_ROOT}/new-remote.md'], b'Remote new')

    def test_recreated_repository_does_not_reuse_old_deletion_baseline(self):
        old = {**REPOSITORY, 'id': 41}
        self.state.save_baseline(self.state.binding(old), {'a.md': b'Local'})
        (self.root / 'a.md').write_bytes(b'Local')
        api = MemoryGitHub({})
        self.synchronize(api)
        self.assertEqual(api.files[f'{SYNC_ROOT}/a.md'], b'Local')

    def test_unsafe_remote_paths_are_rejected_before_writing_any_file(self):
        for name in ('../outside', '/absolute', '.git/config', 'CON', 'a\\b', 'a:stream'):
            with self.subTest(name=name):
                api = MemoryGitHub({name: b'Unsafe'})
                with self.assertRaises(Exception):
                    self.synchronize(api)
                self.assertEqual(local_snapshot(self.root), {})
                self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_identical_content_is_uploaded_only_once_for_multiple_files(self):
        api = MemoryGitHub({})
        (self.root / 'a').write_bytes(b'Shared')
        (self.root / 'b').write_bytes(b'Shared')
        self.synchronize(api)
        uploads = [path for method, path, _ in api.calls if method == 'POST' and path.endswith('/git/blobs')]
        self.assertEqual(len(uploads), 1)

    def test_system_guide_is_not_uploaded_restored_or_left_in_user_backup(self):
        folder = self.root / 'projetos' / 'guia-do-docs-local'
        folder.mkdir(parents=True)
        (folder / 'index.md').write_text('# Local system guide', encoding='utf-8')
        self.assertEqual(local_snapshot(self.root), {})
        api = MemoryGitHub({'projetos/guia-do-docs-local/skill.md': b'# Old backup guide',
                            'projetos/user/index.md': b'# User content'})
        self.synchronize(api)
        self.assertFalse((folder / 'skill.md').exists())
        self.assertNotIn(f'{SYNC_ROOT}/projetos/guia-do-docs-local/skill.md', api.files)
        self.assertNotIn(f'{SYNC_ROOT}/projetos/guia-do-docs-local/index.md', api.files)
        self.assertEqual(api.files[f'{SYNC_ROOT}/projetos/user/index.md'], b'# User content')
        self.assertEqual((folder / 'index.md').read_text(encoding='utf-8'), '# Local system guide')

    def test_system_files_never_enter_the_persistent_backup_queue(self):
        files = {'projetos/guia-do-docs-local/skill.md': b'# System guide'}
        binding = self.state.binding(REPOSITORY)
        self.state.save_baseline(binding, files)
        self.assertEqual(self.state.baseline(binding), {})
        self.assertEqual(self.state.pending_paths(files, binding), [])

    def test_invalid_marker_prevents_restore_and_upload(self):
        api = MemoryGitHub({'a': b'Remote'})
        api.files[MARKER_PATH] = b'Wrong marker'
        with self.assertRaisesRegex(RuntimeError, 'marcador'):
            self.synchronize(api)
        self.assertEqual(local_snapshot(self.root), {})

    def test_legacy_backup_marker_is_migrated_after_restoring_existing_files(self):
        from app.services.backup_sync import LEGACY_MARKER_PATH
        api = MemoryGitHub({'a.md': b'Existing backup'})
        api.files[LEGACY_MARKER_PATH] = api.files.pop(MARKER_PATH)
        self.synchronize(api)
        self.assertEqual((self.root / 'a.md').read_bytes(), b'Existing backup')
        self.assertEqual(api.files[MARKER_PATH], MARKER_CONTENT)
        self.assertNotIn(LEGACY_MARKER_PATH, api.files)

    def test_cleaned_queue_returns_to_synced_without_network(self):
        service = GitHubSync(self.state.folder.parent)
        service._needs_restore = False
        service.status['state'] = 'queued'
        with patch.object(github_service, 'REPO', self.root), patch.object(github_service, 'github_api') as api:
            asyncio.run(service._sync_once())
        self.assertEqual(service.status['state'], 'synced')
        api.assert_not_called()

    def test_clean_queue_and_status_reads_make_no_github_requests(self):
        service = GitHubSync(self.state.folder.parent)
        service._needs_restore = False
        self.state.save_session({'login': 'octocat'}, REPOSITORY)
        self.state.save_baseline(self.state.binding(REPOSITORY), {})
        with (
            patch.object(github_service, 'REPO', self.root),
            patch.object(service, 'is_authenticated', return_value=True),
            patch.object(github_service, 'github_api') as api,
        ):
            async def read_idle_state():
                for _ in range(10):
                    await service.trigger(0)
                    await service.authentication_status()
                    await service.status_details()
            asyncio.run(read_idle_state())
        api.assert_not_called()
        self.assertIsNone(service.worker)

    def test_offline_changes_are_persisted_and_queue_events_are_coalesced(self):
        (self.root / 'a.md').write_bytes(b'Pending')
        service = GitHubSync(self.state.folder.parent)
        with (
            patch.object(github_service, 'REPO', self.root),
            patch.object(service, 'is_authenticated', return_value=False),
        ):
            asyncio.run(service.trigger())
        self.assertEqual(json.loads((self.state.folder / 'outbox.json').read_text())['paths'], ['a.md'])
        with (
            patch.object(github_service, 'REPO', self.root),
            patch.object(service, 'is_authenticated', return_value=True),
            patch.object(service, 'start'),
        ):
            async def enqueue_many():
                for _ in range(20):
                    await service.trigger()
            asyncio.run(enqueue_many())
        self.assertEqual(service.queue.qsize(), 1)
