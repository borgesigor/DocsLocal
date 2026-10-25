import unittest
import io
import tempfile
from pathlib import Path
import asyncio
from urllib.parse import parse_qs
from unittest.mock import patch

from app.core.exceptions import AppError
from app.services import github_service
from app.services.github_client import GitHubAPIError
from app.services import github_client


class GitHubDeviceAuthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.service = github_service.GitHubSync(Path(self.temporary.name))
        self.clock = patch.object(github_service.time, 'monotonic', return_value=100).start()
        self.addCleanup(patch.stopall)
        self.codes = {
            'device_code': 'private-device-code',
            'user_code': 'ABCD-EFGH',
            'verification_uri': 'https://github.com/login/device',
            'expires_in': 900,
            'interval': 5,
        }
        self.oauth = patch.object(github_service, 'oauth_request', return_value=self.codes).start()
        self.secrets = patch.object(github_service.secret_store, 'write').start()

    def start(self):
        return self.service.start_device_authorization()

    def poll(self, attempt):
        self.clock.return_value += 5
        return self.service.poll_device_authorization(attempt['attempt_id'])

    def test_login_uses_bundled_client_id_without_secret_or_user_configuration(self):
        attempt = self.start()

        self.oauth.assert_called_once_with('device/code', {
            'client_id': 'Ov23lik3T7wS1lMsslVi', 'scope': 'repo read:user',
        })
        self.assertEqual(attempt['user_code'], 'ABCD-EFGH')
        self.assertEqual(attempt['verification_uri'], 'https://github.com/login/device')
        self.assertNotIn('device_code', attempt)
        self.secrets.assert_not_called()

    def test_pending_authorization_obeys_polling_interval(self):
        attempt = self.start()
        self.oauth.return_value = {'error': 'authorization_pending'}
        self.assertEqual(self.service.poll_device_authorization(attempt['attempt_id'])['status'], 'pending')
        self.assertEqual(self.oauth.call_count, 1)

        self.assertEqual(self.poll(attempt)['status'], 'pending')
        self.assertEqual(self.oauth.call_count, 2)
        self.assertEqual(self.oauth.call_args.args[1], {
            'client_id': 'Ov23lik3T7wS1lMsslVi',
            'device_code': 'private-device-code',
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
        })
        self.secrets.assert_not_called()

    def test_slow_down_increases_interval_and_prevents_early_requests(self):
        attempt = self.start()
        self.oauth.return_value = {'error': 'slow_down'}
        self.assertEqual(self.poll(attempt)['retry_after'], 10)
        self.poll(attempt)
        self.assertEqual(self.oauth.call_count, 2)

    def test_success_validates_profile_before_storing_token(self):
        attempt = self.start()
        self.oauth.return_value = {'access_token': 'access-token'}
        with (
            patch.object(github_service, 'github_api', return_value={'login': 'octocat'}),
            patch.object(self.service, '_ensure_repository', return_value={'id': 42, 'full_name': 'octocat/docs-local-backup'}),
        ):
            self.assertEqual(self.poll(attempt), {'status': 'authenticated'})
        self.secrets.assert_called_once_with(
            access_token='access-token', refresh_token=None, expires_at=None,
        )
        self.assertEqual(self.service.status['state'], 'idle')
        with self.assertRaises(AppError):
            self.poll(attempt)

    def test_profile_failure_does_not_store_token(self):
        attempt = self.start()
        self.oauth.return_value = {'access_token': 'access-token'}
        with patch.object(github_service, 'github_api', side_effect=GitHubAPIError(401, 'Unauthorized')):
            with self.assertRaises(GitHubAPIError):
                self.poll(attempt)
        self.secrets.assert_not_called()

    def test_denied_or_expired_authorization_cannot_be_reused(self):
        for error in ('access_denied', 'expired_token'):
            with self.subTest(error=error):
                self.oauth.return_value = self.codes
                attempt = self.start()
                self.oauth.return_value = {'error': error}
                with self.assertRaises(AppError):
                    self.poll(attempt)
                with self.assertRaises(AppError):
                    self.poll(attempt)
        self.secrets.assert_not_called()

    def test_local_expiration_does_not_contact_github(self):
        attempt = self.start()
        self.clock.return_value = 1000
        with self.assertRaises(AppError) as error:
            self.service.poll_device_authorization(attempt['attempt_id'])
        self.assertEqual(error.exception.code, 'github_device_expired')
        self.assertEqual(self.oauth.call_count, 1)

    def test_cancelled_and_replaced_attempts_cannot_log_in(self):
        first = self.start()
        second = self.start()
        with self.assertRaises(AppError):
            self.poll(first)
        self.service.cancel_device_authorization(first['attempt_id'])
        self.service.cancel_device_authorization(second['attempt_id'])
        with self.assertRaises(AppError):
            self.poll(second)
        self.assertEqual(self.oauth.call_count, 2)

    def test_logout_invalidates_pending_login(self):
        attempt = self.start()
        self.service.logout()
        with self.assertRaises(AppError):
            self.poll(attempt)

    def test_cancel_during_exchange_or_profile_lookup_does_not_save_session(self):
        for phase in ('exchange', 'profile'):
            with self.subTest(phase=phase):
                self.oauth.return_value = self.codes
                attempt = self.start()

                def exchange(*args):
                    if phase == 'exchange':
                        self.service.cancel_device_authorization(attempt['attempt_id'])
                    return {'access_token': 'access-token'}

                def profile(*args, **kwargs):
                    if phase == 'profile':
                        self.service.cancel_device_authorization(attempt['attempt_id'])
                    return {'login': 'octocat'}

                with (
                    patch.object(github_service, 'oauth_request', side_effect=exchange),
                    patch.object(github_service, 'github_api', side_effect=profile),
                    patch.object(self.service, '_ensure_repository'),
                ):
                    with self.assertRaises(AppError):
                        self.poll(attempt)
                self.secrets.assert_not_called()

    def test_disabled_device_flow_explains_publisher_configuration(self):
        self.oauth.return_value = {'error': 'device_flow_disabled'}
        with self.assertRaises(AppError) as error:
            self.start()
        self.assertIn('Enable Device Flow', error.exception.message)

    def test_untrusted_verification_url_is_rejected(self):
        self.codes['verification_uri'] = 'https://example.invalid/phishing'
        with self.assertRaises(AppError):
            self.start()

    def test_http_slow_down_response_is_handled_without_losing_the_attempt(self):
        attempt = self.start()
        self.oauth.side_effect = GitHubAPIError(400, 'Slow down', code='slow_down')
        self.assertEqual(self.poll(attempt)['retry_after'], 10)

    def test_refresh_uses_bundled_client_id_without_client_secret(self):
        values = {'access_token': 'old', 'expires_at': '1', 'refresh_token': 'refresh'}
        self.oauth.return_value = {'access_token': 'new'}
        with patch.object(github_service.secret_store, 'get', side_effect=values.get):
            self.assertEqual(self.service._access_token(), 'new')
        self.assertEqual(self.oauth.call_args.args[1], {
            'client_id': 'Ov23lik3T7wS1lMsslVi',
            'grant_type': 'refresh_token',
            'refresh_token': 'refresh',
        })

    def test_fresh_installation_is_ready_for_login_without_credentials(self):
        with patch.object(github_service.secret_store, 'get', return_value=None):
            status = asyncio.run(self.service.authentication_status())
        self.assertTrue(status['configured'])
        self.assertFalse(status['authenticated'])
        self.assertNotIn('client_id', status)


class GitHubDeviceTransportTests(unittest.TestCase):
    def test_device_code_and_token_requests_use_the_correct_github_endpoints(self):
        for path, url in (
            ('device/code', 'https://github.com/login/device/code'),
            ('access_token', 'https://github.com/login/oauth/access_token'),
        ):
            with self.subTest(path=path):
                with patch.object(github_client, 'urlopen', return_value=io.BytesIO(b'{}')) as open_request:
                    github_client.oauth_request(path, {'client_id': 'public-id'})
                request = open_request.call_args.args[0]
                self.assertEqual(request.full_url, url)
                self.assertEqual(request.method, 'POST')
                self.assertEqual(parse_qs(request.data.decode()), {'client_id': ['public-id']})
