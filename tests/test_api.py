import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import main
from app.api import routes
from app.core import config
from app.services import git_service, instance_lock, project_service


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.test_root = Path(self.temporary_folder.name)
        self.repository = self.test_root / 'repository'
        self.projects_folder = self.repository / 'projetos'
        self.state_folder = self.test_root / 'state'
        self.projects_folder.mkdir(parents=True)
        self.state_folder.mkdir(parents=True)

        self.patches = [
            patch.object(main, 'REPO', self.repository),
            patch.object(main, 'PROJECTS', self.projects_folder),
            patch.object(main, 'STATE', self.state_folder),
            patch.object(routes, 'REPO', self.repository),
            patch.object(routes, 'PROJECTS', self.projects_folder),
            patch.object(project_service, 'PROJECTS', self.projects_folder),
            patch.object(git_service, 'REPO', self.repository),
            patch.object(git_service, 'STATE', self.state_folder),
            patch.object(git_service, 'STATUS_FILE', self.state_folder / 'sync.json'),
            patch.object(instance_lock, 'STATE', self.state_folder),
            patch.dict(config.CONFIG['git'], {'enabled': False}),
            patch.dict(config.CONFIG['github'], {'enabled': False}),
        ]
        for active_patch in self.patches:
            active_patch.start()

        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temporary_folder.cleanup()

    def test_health_static_and_openapi_endpoints_are_available(self):
        self.assertEqual(self.client.get('/api/v1/health').json()['status'], 'ok')
        self.assertEqual(self.client.get('/').status_code, 200)
        openapi = self.client.get('/openapi.json').json()
        self.assertIn('/api/v1/projects', openapi['paths'])

    def test_document_urls_serve_the_viewer_on_direct_access_and_refresh(self):
        project = self.client.post('/api/v1/projects', json={'name': 'Projeto'}).json()
        project_id = project['id']
        self.client.post(
            f'/api/v1/projects/{project_id}/documents',
            json={'path': 'docs/guias/regras para agentes.md', 'content': '# Regras\n'},
        ).raise_for_status()

        for path in (
            f'/{project_id}',
            f'/{project_id}/index.md',
            f'/{project_id}/docs/guias/regras%20para%20agentes.md',
        ):
            with self.subTest(path=path):
                for _ in range(2):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('text/html', response.headers['content-type'])
                    self.assertEqual(response.content, self.client.get('/').content)

    def test_document_urls_do_not_expose_other_files_or_hide_missing_api_routes(self):
        project = self.client.post('/api/v1/projects', json={'name': 'Projeto'}).json()
        project_id = project['id']
        for path in (
            f'/{project_id}/project.toml',
            f'/{project_id}/assets/segredo.txt',
            f'/{project_id}/docs/ausente.md',
            '/projeto-inexistente/index.md',
            '/api/v1/rota-inexistente',
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('text/html', response.headers['content-type'])

        traversal = self.client.get(f'/{project_id}/docs/%2E%2E/%2E%2E/config.toml')
        self.assertIn(traversal.status_code, (400, 404, 422))

    def test_legacy_document_links_and_openapi_still_work(self):
        response = self.client.get('/?project=projeto&document=document-id')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['content-type'])
        self.assertEqual(self.client.get('/docs').status_code, 200)
        self.assertEqual(self.client.get('/openapi.json').status_code, 200)

    def test_github_oauth_routes_delegate_to_sync_service(self):
        with (
            patch.object(
                routes.sync_manager,
                'authentication_status',
                new=AsyncMock(
                    return_value={
                        'configured': False,
                        'authenticated': False,
                        'callback_url': 'http://127.0.0.1:8765/api/v1/github/auth/callback',
                        'user': None,
                        'repository': None,
                        'repository_error': None,
                    }
                ),
            ),
            patch.object(
                routes.sync_manager,
                'configure_oauth',
                return_value={'configured': True},
            ) as configure_oauth,
            patch.object(
                routes.sync_manager,
                'start_authorization',
                return_value='https://github.com/login/oauth/authorize?state=test',
            ),
            patch.object(
                routes.sync_manager,
                'authentication_callback',
                new=AsyncMock(),
            ) as authentication_callback,
            patch.object(routes.sync_manager, 'logout') as logout,
        ):
            status = self.client.get('/api/v1/github/auth/status')
            configured = self.client.put(
                '/api/v1/github/auth/config',
                json={'client_id': 'client-id', 'client_secret': 'client-secret'},
            )
            authorization = self.client.get('/api/v1/github/auth/start')
            callback = self.client.get(
                '/api/v1/github/auth/callback',
                params={'code': 'oauth-code', 'state': 'oauth-state'},
                follow_redirects=False,
            )
            signed_out = self.client.delete('/api/v1/github/auth')

        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()['authenticated'])
        self.assertEqual(configured.status_code, 200)
        configure_oauth.assert_called_once_with('client-id', 'client-secret')
        self.assertEqual(authorization.json()['authorization_url'].split('?')[0], 'https://github.com/login/oauth/authorize')
        self.assertEqual(callback.status_code, 303)
        self.assertEqual(callback.headers['location'], '/?github=connected')
        authentication_callback.assert_awaited_once_with(
            code='oauth-code',
            state='oauth-state',
            error=None,
        )
        self.assertEqual(signed_out.json(), {'authenticated': False})
        logout.assert_called_once_with()

    def test_project_document_search_and_revision_api(self):
        response = self.client.post(
            '/api/v1/projects',
            json={'name': 'Projeto de API', 'description': 'Notas locais'},
        )
        self.assertEqual(response.status_code, 201)
        project_id = response.json()['id']

        created = self.client.post(
            f'/api/v1/projects/{project_id}/documents',
            json={
                'path': 'docs/notas.md',
                'title': 'Notas',
                'content': '# Notas\n\ntermo pesquisável',
            },
        )
        self.assertEqual(created.status_code, 201)
        document_id = created.json()['id']
        self.assertEqual(created.json()['revision'], 1)

        stale_write_without_revision = self.client.put(
            f'/api/v1/projects/{project_id}/documents/{document_id}',
            json={'content': 'conteúdo novo'},
        )
        self.assertEqual(stale_write_without_revision.status_code, 428)

        saved = self.client.put(
            f'/api/v1/projects/{project_id}/documents/{document_id}',
            json={'content': '# Notas\n\ntermo pesquisável atualizado', 'revision': 1},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['revision'], 2)

        search = self.client.get('/api/v1/search', params={'q': 'pesquisável'})
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()[0]['project_id'], project_id)

        stale_write = self.client.put(
            f'/api/v1/projects/{project_id}/documents/{document_id}',
            json={'content': 'sobrescrita obsoleta', 'revision': 1},
        )
        self.assertEqual(stale_write.status_code, 409)

    def test_path_traversal_and_untrusted_origins_are_rejected(self):
        project = self.client.post('/api/v1/projects', json={'name': 'Isolamento'}).json()
        project_id = project['id']
        traversal = self.client.post(
            f'/api/v1/projects/{project_id}/documents',
            json={'path': '../../outside.md'},
        )
        self.assertEqual(traversal.status_code, 422)

        invalid_character = self.client.post(
            f'/api/v1/projects/{project_id}/documents',
            json={'path': 'docs/guia?.md'},
        )
        self.assertEqual(invalid_character.status_code, 422)

        reserved_filename = self.client.post(
            f'/api/v1/projects/{project_id}/documents',
            json={'path': 'docs/CON.md'},
        )
        self.assertEqual(reserved_filename.status_code, 422)

        reserved_folder = self.client.post(
            f'/api/v1/projects/{project_id}/folders',
            json={'path': 'docs/LPT1'},
        )
        self.assertEqual(reserved_folder.status_code, 422)

        foreign_origin = self.client.post(
            '/api/v1/projects',
            json={'name': 'Origem externa'},
            headers={'Origin': 'https://attacker.invalid'},
        )
        self.assertEqual(foreign_origin.status_code, 403)

    def test_archiving_and_local_attachment_endpoints(self):
        project = self.client.post('/api/v1/projects', json={'name': 'Arquivos'}).json()
        project_id = project['id']

        renamed = self.client.patch(
            f'/api/v1/projects/{project_id}',
            json={'name': '  Arquivos atualizados  '},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()['name'], 'Arquivos atualizados')
        empty_name = self.client.patch(
            f'/api/v1/projects/{project_id}',
            json={'name': '   '},
        )
        self.assertEqual(empty_name.status_code, 422)

        uploaded = self.client.post(
            f'/api/v1/projects/{project_id}/files',
            files={'file': ('nota.txt', b'conteudo', 'text/plain')},
        )
        self.assertEqual(uploaded.status_code, 201)
        listed_files = self.client.get(f'/api/v1/projects/{project_id}/files').json()
        self.assertEqual(listed_files[0]['path'], 'nota.txt')

        unconfirmed_archive = self.client.delete(f'/api/v1/projects/{project_id}')
        self.assertEqual(unconfirmed_archive.status_code, 400)
        archived = self.client.delete(f'/api/v1/projects/{project_id}?confirm=true')
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(self.client.get('/api/v1/projects').json(), [])

    def test_document_and_folder_context_actions_use_api_routes(self):
        project = self.client.post(
            '/api/v1/projects',
            json={'name': 'Ações da árvore'},
        ).json()
        project_id = project['id']

        created_folder = self.client.post(
            f'/api/v1/projects/{project_id}/folders',
            json={'path': 'docs/guias'},
        )
        self.assertEqual(created_folder.status_code, 201)

        renamed_folder = self.client.patch(
            f'/api/v1/projects/{project_id}/folders',
            json={'path': 'docs/guias', 'new_path': 'docs/manual'},
        )
        self.assertEqual(renamed_folder.status_code, 200)
        self.assertEqual(renamed_folder.json()['path'], 'docs/manual')

        document = self.client.post(
            f'/api/v1/projects/{project_id}/documents',
            json={'path': 'docs/manual/instalacao.md', 'title': 'Instalação'},
        ).json()
        renamed_document = self.client.patch(
            f"/api/v1/projects/{project_id}/documents/{document['id']}",
            json={
                'path': 'docs/manual/configuracao.md',
                'title': 'Configuração',
            },
        )
        self.assertEqual(renamed_document.status_code, 200)
        self.assertEqual(
            renamed_document.json()['path'],
            'docs/manual/configuracao.md',
        )
        self.assertEqual(renamed_document.json()['title'], 'Configuração')

        renamed_with_other_extension = self.client.patch(
            f"/api/v1/projects/{project_id}/documents/{document['id']}",
            json={
                'path': 'docs/manual/configuracao.txt',
                'title': 'Configuração',
            },
        )
        self.assertEqual(renamed_with_other_extension.status_code, 200)
        self.assertEqual(
            renamed_with_other_extension.json()['path'],
            'docs/manual/configuracao.md',
        )

        nested_folder = self.client.post(
            f'/api/v1/projects/{project_id}/folders',
            json={'path': 'docs/manual/referencias'},
        )
        self.assertEqual(nested_folder.status_code, 201)

        child_document = self.client.post(
            f'/api/v1/projects/{project_id}/documents',
            json={
                'path': 'docs/manual/referencias/fontes.md',
                'title': 'Fontes',
            },
        )
        self.assertEqual(child_document.status_code, 201)

        deleted_folder = self.client.delete(
            f'/api/v1/projects/{project_id}/folders',
            params={'path': 'docs/manual'},
        )
        self.assertEqual(deleted_folder.status_code, 200)
        project_folder = self.projects_folder / project_id
        self.assertFalse((project_folder / 'docs' / 'manual').exists())
        self.assertFalse(
            (
                project_folder
                / 'docs'
                / 'manual'
                / 'referencias'
                / 'fontes.md'
            ).exists()
        )


if __name__ == '__main__':
    unittest.main()
