from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from unittest.mock import patch

from tests import test_api, test_services
from app.core.exceptions import AppError
from app.services import document_service as documents, project_service as projects


class ConcurrentStorageTests(unittest.TestCase):
    setUp = test_services.StorageTests.setUp
    tearDown = test_services.StorageTests.tearDown

    def race(self, operation):
        barrier = Barrier(8)

        def run(writer):
            barrier.wait(timeout=10)
            try:
                return operation(writer)
            except AppError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(run, range(8)))

    def test_concurrent_document_creates_preserve_every_winner(self):
        project_id = projects.create_project('Concurrent')['id']
        for round_number in range(20):
            with self.subTest(round=round_number):
                results = self.race(lambda writer: documents.create_document(
                    project_id, f'docs/distinct-{round_number}-{writer}.md', content=str(writer)
                ))
                for writer, result in enumerate(results):
                    self.assertEqual(documents.read_document(project_id, result['id'])['content'], str(writer))
                results = self.race(lambda writer: documents.create_document(
                    project_id, f'docs/same-{round_number}.md', content=str(writer)
                ))
                winners = [result for result in results if isinstance(result, dict)]
                self.assertEqual(len(winners), 1)
                self.assertEqual(results.count(409), 7)
                self.assertEqual(documents.read_document(project_id, winners[0]['id']), winners[0])

    def test_concurrent_projects_have_complete_unique_directories(self):
        for _ in range(20):
            results = self.race(lambda _: projects.create_project('Race'))
            self.assertEqual(len({result['id'] for result in results}), 8)
            for result in results:
                folder, _ = projects.get_folder(result['id'])
                self.assertTrue((folder / 'index.md').is_file())
                self.assertTrue((folder / 'docs').is_dir())
                self.assertTrue((folder / 'assets').is_dir())

    def test_failed_metadata_update_rolls_back_document_changes(self):
        project_id = projects.create_project('Rollback')['id']
        document = documents.create_document(project_id, 'docs/existing.md', content='original')
        folder, _ = projects.get_folder(project_id)
        original_bytes = (folder / document['path']).read_bytes()
        with patch.object(projects, 'touch_project', side_effect=OSError('metadata unavailable')):
            with self.assertRaises(OSError):
                documents.create_document(project_id, 'docs/new.md')
            self.assertFalse((folder / 'docs/new.md').exists())
            with self.assertRaises(OSError):
                documents.update_document(project_id, document['id'], 'changed', 1, 'docs/moved.md')
            self.assertEqual((folder / document['path']).read_bytes(), original_bytes)
            self.assertFalse((folder / 'docs/moved.md').exists())
            with self.assertRaises(OSError):
                documents.delete_document(project_id, document['id'])
            self.assertEqual((folder / document['path']).read_bytes(), original_bytes)

    def test_failed_project_initialization_removes_partial_directory(self):
        with patch.object(projects, 'atomic_write', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                projects.create_project('Partial')
        self.assertEqual(list(self.projects_root.iterdir()), [])


class IntegrityAndOriginTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown

    def test_windows_reserved_project_names_are_rejected_before_creation(self):
        for name in ('NUL', 'CON', 'COM1', 'LPT1'):
            with self.subTest(name=name):
                response = self.client.post('/api/v1/projects', json={'name': name})
                self.assertEqual(response.status_code, 422)
        self.assertEqual(list(self.projects_folder.iterdir()), [])

    def test_index_cannot_move_and_missing_index_is_reported(self):
        project = projects.create_project('Index')
        index = documents.list_documents(project['id'])[0]
        response = self.client.patch(
            f"/api/v1/projects/{project['id']}/documents/{index['id']}",
            json={'path': 'docs/moved.md'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(documents.read_document(project['id'], index['id'])['path'], 'index.md')
        (self.projects_folder / project['id'] / 'index.md').unlink()
        result = self.client.get('/api/v1/system/integrity').json()
        self.assertFalse(result['ok'])
        self.assertTrue(any(issue['path'] == 'index.md' for issue in result['issues']))

    def test_corrupt_documents_leave_healthy_content_accessible(self):
        project_id = projects.create_project('Corrupt')['id']
        corrupt_path = self.projects_folder / project_id / 'docs/corrupt.md'
        corrupt_path.write_bytes(b'\xff\xfe\x00')
        healthy = documents.create_document(project_id, 'docs/healthy.md', content='# Healthy needle')
        for endpoint in (f'/projects/{project_id}/documents', f'/projects/{project_id}/tree', '/search?q=needle'):
            response = self.client.get('/api/v1' + endpoint)
            self.assertEqual(response.status_code, 200)
            self.assertIn('Healthy', response.text)
        self.assertEqual(documents.read_document(project_id, healthy['id']), healthy)
        response = self.client.get('/api/v1/system/integrity')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['ok'])
        self.assertTrue(any(issue['path'] == 'docs/corrupt.md' for issue in response.json()['issues']))
        self.assertEqual(corrupt_path.read_bytes(), b'\xff\xfe\x00')

    def test_integrity_includes_malformed_and_archived_projects(self):
        archived = projects.create_project('Archived')
        projects.delete_project(archived['id'])
        folder = self.projects_folder / 'malformed'
        folder.mkdir()
        (folder / 'project.toml').write_text('not valid = [', encoding='utf-8')
        self.assertEqual(self.client.get('/api/v1/projects').json(), [])
        result = self.client.get('/api/v1/system/integrity').json()
        self.assertFalse(result['ok'])
        self.assertEqual(result['projects'], 2)
        self.assertTrue(any(issue['project_id'] == 'malformed' and issue['path'] == 'project.toml' for issue in result['issues']))

    def test_invalid_metadata_values_are_reported_without_breaking_lists(self):
        folder = self.projects_folder / 'damaged'
        folder.mkdir()
        for metadata in (b'\xff\xfe', b'name = 123', b'id="other"\nslug="damaged"\nname="Damaged"'):
            with self.subTest(metadata=metadata):
                (folder / 'project.toml').write_bytes(metadata)
                self.assertEqual(self.client.get('/api/v1/projects').json(), [])
                result = self.client.get('/api/v1/system/integrity').json()
                self.assertFalse(result['ok'])
                self.assertTrue(any(issue['path'] == 'project.toml' for issue in result['issues']))

    def test_mutations_require_same_origin_and_json_content_type(self):
        for origin in ('http://testserver:3000', 'https://testserver', 'http://localhost:3000', 'null', 'http://testserver:bad', 'http://[broken', 'http://testserver/foreign'):
            response = self.client.post('/api/v1/projects', json={'name': 'Rejected'}, headers={'Origin': origin})
            self.assertEqual(response.status_code, 403, origin)
        for origin in ('http://testserver', 'http://testserver:80'):
            response = self.client.post('/api/v1/projects', json={'name': 'Accepted'}, headers={'Origin': origin})
            self.assertEqual(response.status_code, 201)
        project_id = projects.create_project('Content type')['id']
        for endpoint, payload in (('/projects', '{"name":"Plain"}'), (f'/projects/{project_id}/folders', '{"path":"docs/plain"}')):
            response = self.client.post('/api/v1' + endpoint, content=payload, headers={'Content-Type': 'text/plain'})
            self.assertEqual(response.status_code, 415)
        self.assertFalse((self.projects_folder / project_id / 'docs/plain').exists())
