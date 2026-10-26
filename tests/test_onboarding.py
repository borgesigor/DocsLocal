import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.exceptions import AppError
from app.services import document_service, project_service
from app.services.onboarding_service import ensure_welcome_documentation


class WelcomeDocumentationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.projects = self.root / 'projetos'
        self.state = self.root / 'state'
        patcher = patch.object(project_service, 'PROJECTS', self.projects)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_first_start_creates_readable_guide_without_github(self):
        ensure_welcome_documentation(self.state)

        projects = project_service.list_projects()
        self.assertEqual(len(projects), 1)
        project = projects[0]
        self.assertEqual(project['name'], 'Guia do Docs Local')
        documents = document_service.list_documents(project['id'])
        self.assertGreaterEqual(len(documents), 4)
        guide = document_service.read_document(project['id'], documents[0]['id'])
        self.assertEqual(guide['path'], 'index.md')
        for topic in ('Markdown', 'projeto', 'GitHub', 'backup', 'offline', 'API'):
            self.assertIn(topic, guide['content'])

    def test_restart_preserves_user_edits_and_does_not_duplicate_guide(self):
        ensure_welcome_documentation(self.state)
        project = project_service.list_projects()[0]
        document = document_service.list_documents(project['id'])[0]
        document_service.update_document(project['id'], document['id'], '# Meu guia', 1)

        ensure_welcome_documentation(self.state)

        self.assertEqual(len(project_service.list_projects()), 1)
        saved = document_service.read_document(project['id'], document['id'])
        self.assertEqual(saved['content'], '# Meu guia')
        self.assertEqual(saved['revision'], 2)

    def test_default_guide_and_all_its_documents_cannot_be_deleted(self):
        ensure_welcome_documentation(self.state)
        project = project_service.list_projects()[0]
        with self.assertRaises(AppError):
            project_service.delete_project(project['id'])
        with self.assertRaises(AppError):
            project_service.update_project(project['id'], {'archived': True})
        for document in document_service.list_documents(project['id']):
            with self.assertRaises(AppError):
                document_service.delete_document(project['id'], document['id'])
        self.assertEqual(len(project_service.list_projects()), 1)

    def test_guide_contains_internal_url_and_complete_agent_skill(self):
        ensure_welcome_documentation(self.state)
        project = project_service.list_projects()[0]
        docs = {doc['path']: document_service.read_document(project['id'], doc['id'])
                for doc in document_service.list_documents(project['id'])}
        self.assertIn('http://docs.local', docs['index.md']['content'])
        self.assertIn('docs/skill/SKILL.md', docs['index.md']['content'])
        self.assertIn('name: docslocal', docs['docs/skill/SKILL.md']['content'])
        self.assertIn('http://docs.local', docs['docs/skill/SKILL.md']['content'])
        self.assertIn('docs/skill/references/http-workflow.md', docs)
        self.assertIn('docs/skill/references/api-documentation.md', docs)

    def test_upgrade_protects_existing_guide_without_overwriting_edits(self):
        project = project_service.create_project('Guia do Docs Local', initial_content='# Meu guia')
        self.state.mkdir()
        (self.state / 'welcome-documentation-v1').write_text(project['id'] + '\n')
        ensure_welcome_documentation(self.state)
        folder, metadata = project_service.get_folder(project['id'])
        self.assertTrue(metadata['protected'])
        self.assertIn('# Meu guia', (folder / 'index.md').read_text(encoding='utf-8'))
        self.assertIn('http://docs.local', (folder / 'index.md').read_text(encoding='utf-8'))
        self.assertTrue((folder / 'docs/skill/SKILL.md').exists())

    def test_upgrade_reactivates_a_guide_archived_by_an_older_version(self):
        project = project_service.create_project('Guia do Docs Local')
        project_service.delete_project(project['id'])
        self.state.mkdir()
        (self.state / 'welcome-documentation-v1').write_text(project['id'] + '\n')
        ensure_welcome_documentation(self.state)
        restored = project_service.list_projects()
        self.assertEqual([item['id'] for item in restored], [project['id']])
        self.assertTrue(restored[0]['protected'])

    def test_guide_deleted_by_an_older_version_is_recreated(self):
        self.state.mkdir()
        (self.state / 'welcome-documentation-v1').write_text('missing-guide\n')
        ensure_welcome_documentation(self.state)
        self.assertEqual(len(project_service.list_projects()), 1)
        self.assertTrue(project_service.list_projects()[0]['protected'])

    def test_old_backup_restore_receives_protection_and_skill_again(self):
        from app.services.storage import atomic_write
        from app.services.toml_writer import dumps_values
        ensure_welcome_documentation(self.state)
        project = project_service.list_projects()[0]
        folder, metadata = project_service.get_folder(project['id'])
        metadata.pop('protected')
        atomic_write(folder / 'project.toml', dumps_values(metadata))
        atomic_write(folder / 'index.md', '# Guia recuperado do backup\n')
        ensure_welcome_documentation(self.state)
        self.assertTrue(project_service.get_folder(project['id'])[1]['protected'])
        self.assertIn('# Guia recuperado do backup', (folder / 'index.md').read_text(encoding='utf-8'))
        self.assertIn('http://docs.local', (folder / 'index.md').read_text(encoding='utf-8'))

    def test_existing_project_with_same_name_is_preserved(self):
        original = project_service.create_project('Guia do Docs Local', 'Meu projeto')

        ensure_welcome_documentation(self.state)

        self.assertEqual(len(project_service.list_projects()), 2)
        _, metadata = project_service.get_folder(original['id'])
        self.assertEqual(metadata['description'], 'Meu projeto')

    def test_application_startup_initializes_the_guide(self):
        from app import main

        async def start_application():
            async with main.lifespan(main.app):
                self.assertEqual(project_service.list_projects()[0]['name'], 'Guia do Docs Local')
                self.assertTrue((self.state / 'welcome-documentation-v1').is_file())

        with (
            patch.object(main, 'REPO', self.root / 'repository'),
            patch.object(main, 'PROJECTS', self.projects),
            patch.object(main, 'STATE', self.state),
            patch.object(main.instance_lock, 'acquire'),
            patch.object(main.instance_lock, 'release'),
            patch.object(main.sync_manager, 'start'),
            patch.object(main.sync_manager, 'worker', None),
            patch.dict(main.CONFIG['github'], {'enabled': False}),
        ):
            asyncio.run(start_application())
