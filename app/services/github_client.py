"""Small GitHub REST and OAuth client built on Python's standard library."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = 'https://api.github.com'
OAUTH_ROOT = 'https://github.com/login/oauth'
API_VERSION = '2026-03-10'
REQUEST_TIMEOUT_SECONDS = 20


class GitHubAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _request_json(
    url: str,
    *,
    method: str = 'GET',
    data: dict | None = None,
    token: str | None = None,
    accept: str = 'application/vnd.github+json',
) -> dict | list:
    headers = {
        'Accept': accept,
        'User-Agent': 'Docs-Local',
        'X-GitHub-Api-Version': API_VERSION,
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = None
    if data is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(data).encode('utf-8')

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as error:
        payload = error.read()
        try:
            details = json.loads(payload.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            details = {}
        message = details.get('message') or f'GitHub retornou HTTP {error.code}.'
        code = details.get('error') if isinstance(details, dict) else None
        raise GitHubAPIError(error.code, str(message), code) from error
    except (TimeoutError, URLError) as error:
        raise GitHubAPIError(503, 'Não foi possível conectar ao GitHub.') from error

    if not payload:
        return {}
    try:
        result = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GitHubAPIError(502, 'O GitHub retornou uma resposta inválida.') from error
    if not isinstance(result, (dict, list)):
        raise GitHubAPIError(502, 'O GitHub retornou uma resposta inesperada.')
    return result


def github_api(
    path: str,
    *,
    method: str = 'GET',
    data: dict | None = None,
    token: str | None = None,
) -> dict | list:
    return _request_json(
        f'{API_ROOT}{path}',
        method=method,
        data=data,
        token=token,
    )


def oauth_request(path: str, values: dict[str, str]) -> dict:
    request = Request(
        f'{OAUTH_ROOT}/{path}',
        data=urlencode(values).encode('ascii'),
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Docs-Local',
        },
        method='POST',
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except HTTPError as error:
        payload = error.read()
        try:
            result = json.loads(payload.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            result = {}
        message = result.get('error_description') or result.get('error')
        if not message:
            message = f'GitHub retornou HTTP {error.code} durante o login.'
        raise GitHubAPIError(error.code, str(message), result.get('error')) from error
    except (TimeoutError, URLError) as error:
        raise GitHubAPIError(503, 'Não foi possível conectar ao GitHub.') from error

    try:
        result = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GitHubAPIError(502, 'O GitHub retornou uma resposta inválida.') from error
    if not isinstance(result, dict):
        raise GitHubAPIError(502, 'O GitHub retornou uma resposta inesperada.')
    return result
