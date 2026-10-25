import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from app.core.exceptions import AppError
from app.services import github_service
from app.services.github_client import GitHubAPIError


class GitHubOAuthTests(unittest.TestCase):
    def setUp(self):
        self.service = github_service.GitHubSync()
        self.config_patch = patch.dict(
            github_service.CONFIG['github'],
            {'enabled': True, 'client_id': 'test-client-id', 'repository_name': 'docs-local-backup'},
        )
        self.config_patch.start()

    def tearDown(self):
        self.config_patch.stop()

    def test_authorization_url_uses_local_callback_and_pkce(self):
        with patch.object(github_service.secret_store, 'get', return_value='test-secret'):
            authorization_url = self.service.start_authorization()

        query = parse_qs(urlparse(authorization_url).query)
        self.assertEqual(query['client_id'], ['test-client-id'])
        self.assertEqual(query['redirect_uri'], [self.service.callback_url()])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertTrue(query['code_challenge'][0])
        self.assertIn('repo', query['scope'][0])
        self.assertIn('read:user', query['scope'][0])

    def test_callback_rejects_invalid_state_before_exchanging_code(self):
        with patch.object(github_service.secret_store, 'get', return_value='test-secret'):
            self.service.start_authorization()

        with patch.object(github_service, 'oauth_request') as oauth_request:
            with self.assertRaises(AppError) as error:
                self.service.complete_authorization(
                    code='authorization-code',
                    state='wrong-state',
                )

        self.assertEqual(error.exception.code, 'invalid_oauth_state')
        oauth_request.assert_not_called()

    def test_callback_exchanges_code_and_verifies_profile_and_repository(self):
        stored_values = {'client_secret': 'test-secret'}

        def read_secret(key):
            return stored_values.get(key)

        def save_secrets(**values):
            for key, value in values.items():
                if value:
                    stored_values[key] = value
                else:
                    stored_values.pop(key, None)

        with (
            patch.object(github_service.secret_store, 'get', side_effect=read_secret),
            patch.object(github_service.secret_store, 'write', side_effect=save_secrets),
        ):
            authorization_url = self.service.start_authorization()
            state = parse_qs(urlparse(authorization_url).query)['state'][0]

            with (
                patch.object(
                    github_service,
                    'oauth_request',
                    return_value={'access_token': 'access-token'},
                ) as oauth_request,
                patch.object(
                    github_service,
                    'github_api',
                    side_effect=[
                        {'login': 'octocat', 'avatar_url': 'https://example.invalid/avatar.png'},
                        {
                            'name': 'docs-local-backup',
                            'full_name': 'octocat/docs-local-backup',
                            'html_url': 'https://github.com/octocat/docs-local-backup',
                            'default_branch': 'main',
                            'private': True,
                            'owner': {'login': 'octocat'},
                        },
                    ],
                ) as github_api,
            ):
                self.service.complete_authorization(
                    code='authorization-code',
                    state=state,
                )

        exchange = oauth_request.call_args.args[1]
        self.assertEqual(exchange['code'], 'authorization-code')
        self.assertTrue(exchange['code_verifier'])
        self.assertEqual(stored_values['access_token'], 'access-token')
        self.assertEqual(github_api.call_count, 2)
        self.assertEqual(self.service.status['state'], 'idle')


class GitHubRepositoryTests(unittest.TestCase):
    def test_legacy_marker_is_rejected_when_remote_content_differs_from_local(self):
        service = github_service.GitHubSync()
        local_content = b'local document\n'
        remote_content = b'different remote document\n'
        legacy_marker_path = (
            f'{github_service.SYNC_ROOT}/{github_service.MARKER_PATH}'
        )
        local_remote_paths = {
            f'{github_service.SYNC_ROOT}/folder/document.md': local_content,
            github_service.MARKER_PATH: github_service.MARKER_CONTENT,
        }
        remote_by_path = {
            legacy_marker_path: {
                'sha': service._git_blob_sha(github_service.MARKER_CONTENT),
            },
            f'{github_service.SYNC_ROOT}/folder/document.md': {
                'sha': service._git_blob_sha(remote_content),
            },
        }

        with self.assertRaisesRegex(RuntimeError, 'não vai sobrescrever esse backup'):
            service._validate_legacy_managed_tree(
                remote_by_path,
                local_remote_paths,
                service._git_blob_sha(github_service.MARKER_CONTENT),
            )

    def test_missing_repository_is_created_as_private_and_verified(self):
        service = github_service.GitHubSync()
        missing_repository = GitHubAPIError(404, 'Not Found')
        created_repository = {
            'name': 'docs-local-backup',
            'full_name': 'octocat/docs-local-backup',
            'html_url': 'https://github.com/octocat/docs-local-backup',
            'default_branch': 'main',
            'private': True,
            'owner': {'login': 'octocat'},
        }

        with (
            patch.dict(
                github_service.CONFIG['github'],
                {'repository_name': 'docs-local-backup'},
            ),
            patch.object(
                github_service,
                'github_api',
                side_effect=[missing_repository, created_repository],
            ) as github_api,
        ):
            result = service._ensure_repository({'login': 'octocat'}, 'access-token')

        create_call = github_api.call_args_list[1]
        self.assertEqual(create_call.args[0], '/user/repos')
        self.assertEqual(create_call.kwargs['method'], 'POST')
        self.assertTrue(create_call.kwargs['data']['private'])
        self.assertTrue(create_call.kwargs['data']['auto_init'])
        self.assertEqual(result['full_name'], 'octocat/docs-local-backup')

    def test_public_repository_is_rejected(self):
        service = github_service.GitHubSync()
        repository = {
            'name': 'docs-local-backup',
            'full_name': 'octocat/docs-local-backup',
            'private': False,
            'owner': {'login': 'octocat'},
        }
        with (
            patch.dict(
                github_service.CONFIG['github'],
                {'repository_name': 'docs-local-backup'},
            ),
            patch.object(github_service, 'github_api', return_value=repository),
            self.assertRaisesRegex(RuntimeError, 'precisa ser privado'),
        ):
            service._ensure_repository({'login': 'octocat'}, 'access-token')


if __name__ == '__main__':
    unittest.main()
