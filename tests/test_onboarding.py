import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(len(documents), 1)
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

    def test_restart_does_not_recreate_archived_guide(self):
        ensure_welcome_documentation(self.state)
        project_service.delete_project(project_service.list_projects()[0]['id'])

        ensure_welcome_documentation(self.state)

        self.assertEqual(project_service.list_projects(), [])
        self.assertEqual(len(project_service.list_projects(include_archived=True)), 1)

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
