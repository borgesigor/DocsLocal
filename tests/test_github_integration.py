"""Opt-in integration test against GitHub using a disposable branch.

Run with DOCS_LOCAL_GITHUB_INTEGRATION=1 and a configured, authenticated Docs
Local session. The test deletes its temporary branch after the round-trip.
"""

import asyncio
import base64
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import quote

from app.core.config import CONFIG
from app.services import github_service
from app.services.github_client import github_api
from app.services.github_service import GitHubSync


@unittest.skipUnless(
    os.environ.get('DOCS_LOCAL_GITHUB_INTEGRATION') == '1',
    'Set DOCS_LOCAL_GITHUB_INTEGRATION=1 to run the real GitHub API test.',
)
class GitHubSyncIntegrationTests(unittest.TestCase):
    def test_publishes_local_snapshot_and_reads_it_back_from_github(self):
        service = GitHubSync()
        self.assertTrue(service.is_configured(), 'GitHub OAuth is not configured.')
        self.assertTrue(service.is_authenticated(), 'Log in to GitHub in Docs Local first.')

        token = service._access_token()
        profile = github_api('/user', token=token)
        repository = service._ensure_repository(profile, token)
        owner, repository_name = repository['full_name'].split('/', 1)
        repository_path = (
            f'/repos/{quote(owner, safe="")}/{quote(repository_name, safe="")}'
        )
        test_branch = f'docs-local-integration-{uuid.uuid4().hex[:12]}'
        test_branch_path = quote(test_branch, safe='/')
        branch_created = False

        try:
            seed_blob = github_api(
                f'{repository_path}/git/blobs',
                method='POST',
                token=token,
                data={
                    'content': 'Disposable integration branch seed.\n',
                    'encoding': 'utf-8',
                },
            )
            initial_content = b'# GitHub integration test\n\nInitial snapshot.\n'
            document_blob = github_api(
                f'{repository_path}/git/blobs',
                method='POST',
                token=token,
                data={
                    'content': base64.b64encode(initial_content).decode('ascii'),
                    'encoding': 'base64',
                },
            )
            legacy_marker_blob = github_api(
                f'{repository_path}/git/blobs',
                method='POST',
                token=token,
                data={
                    'content': base64.b64encode(
                        github_service.MARKER_CONTENT
                    ).decode('ascii'),
                    'encoding': 'base64',
                },
            )
            test_file_path = 'docs-local-backup/data/integration-test/roundtrip.md'
            legacy_marker_path = (
                'docs-local-backup/data/docs-local-backup/.docs-local-managed.json'
            )
            seed_tree = github_api(
                f'{repository_path}/git/trees',
                method='POST',
                token=token,
                data={
                    'tree': [
                        {
                            'path': 'README.md',
                            'mode': '100644',
                            'type': 'blob',
                            'sha': seed_blob['sha'],
                        },
                        {
                            'path': test_file_path,
                            'mode': '100644',
                            'type': 'blob',
                            'sha': document_blob['sha'],
                        },
                        {
                            'path': legacy_marker_path,
                            'mode': '100644',
                            'type': 'blob',
                            'sha': legacy_marker_blob['sha'],
                        },
                    ]
                },
            )
            root_commit = github_api(
                f'{repository_path}/git/commits',
                method='POST',
                token=token,
                data={
                    'message': 'test: isolated Docs Local integration branch',
                    'tree': seed_tree['sha'],
                    'parents': [],
                },
            )
            github_api(
                f'{repository_path}/git/refs',
                method='POST',
                token=token,
                data={
                    'ref': f'refs/heads/{test_branch}',
                    'sha': root_commit['sha'],
                },
            )
            branch_created = True

            with tempfile.TemporaryDirectory(prefix='docs-local-github-test-') as temp_dir:
                snapshot_root = Path(temp_dir)
                document = snapshot_root / 'integration-test' / 'roundtrip.md'
                document.parent.mkdir(parents=True)
                document.write_bytes(initial_content)

                with patch.dict(
                    CONFIG['github'],
                    {'repository_name': repository_name},
                ), patch.object(github_service, 'REPO', snapshot_root):
                    with patch.object(
                        service,
                        '_ensure_repository',
                        return_value={**repository, 'default_branch': test_branch},
                    ):
                        asyncio.run(service._sync_once())
                self.assertEqual(service.status['state'], 'synced')
                self.assertTrue(service.status['last_sync'])

                remote_file_path = test_file_path
                stored_file = github_api(
                    f'{repository_path}/contents/{remote_file_path}?ref={test_branch_path}',
                    token=token,
                )
                self.assertEqual(stored_file['encoding'], 'base64')
                actual_content = base64.b64decode(stored_file['content'])
                self.assertEqual(actual_content, initial_content)
                self.assertTrue(stored_file.get('sha'))

                marker = github_api(
                    f'{repository_path}/contents/docs-local-backup/.docs-local-managed.json?ref={test_branch_path}',
                    token=token,
                )
                self.assertEqual(
                    base64.b64decode(marker['content']),
                    github_service.MARKER_CONTENT,
                )

                migrated_tree = github_api(
                    f'{repository_path}/git/refs/heads/{test_branch_path}',
                    token=token,
                )
                migrated_commit = github_api(
                    f'{repository_path}/git/commits/{migrated_tree["object"]["sha"]}',
                    token=token,
                )
                test_branch_tree = github_api(
                    f'{repository_path}/git/trees/{migrated_commit["tree"]["sha"]}?recursive=1',
                    token=token,
                )
                self.assertNotIn(
                    legacy_marker_path,
                    {entry['path'] for entry in test_branch_tree.get('tree', [])},
                )

                updated_content = b'# GitHub integration test\n\nUpdated snapshot.\n'
                document.write_bytes(updated_content)
                with patch.dict(
                    CONFIG['github'],
                    {'repository_name': repository_name},
                ), patch.object(github_service, 'REPO', snapshot_root):
                    with patch.object(
                        service,
                        '_ensure_repository',
                        return_value={**repository, 'default_branch': test_branch},
                    ):
                        asyncio.run(service._sync_once())
                self.assertEqual(service.status['state'], 'synced')

                stored_file = github_api(
                    f'{repository_path}/contents/{remote_file_path}?ref={test_branch_path}',
                    token=token,
                )
                self.assertEqual(
                    base64.b64decode(stored_file['content']),
                    updated_content,
                )

                with patch.dict(
                    CONFIG['github'],
                    {'repository_name': repository_name},
                ), patch.object(github_service, 'REPO', snapshot_root):
                    with patch.object(
                        service,
                        '_ensure_repository',
                        return_value={**repository, 'default_branch': test_branch},
                    ):
                        asyncio.run(service._sync_once())
                self.assertEqual(service.status['state'], 'synced')

                commit_history = github_api(
                    f'{repository_path}/commits?path={remote_file_path}&per_page=1&sha={test_branch_path}',
                    token=token,
                )
                self.assertTrue(commit_history, 'GitHub did not record a commit for the snapshot.')
        finally:
            if branch_created:
                github_api(
                    f'{repository_path}/git/refs/heads/{test_branch_path}',
                    method='DELETE',
                    token=token,
                )


if __name__ == '__main__':
    unittest.main()
