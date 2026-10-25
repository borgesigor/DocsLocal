import unittest
from unittest.mock import patch

from app.services import github_service
from app.services.github_client import GitHubAPIError


class GitHubRepositoryTests(unittest.TestCase):
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
