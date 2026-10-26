import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import SYSTEM_PROJECTS
from app.core.exceptions import AppError
from app.services import document_service, project_service
from app.services.backup_sync import local_snapshot


class SystemProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.user_projects = self.root / 'repository' / 'projetos'
        self.system_projects = self.root / 'system-projects'
        shutil.copytree(SYSTEM_PROJECTS, self.system_projects)
        self.guide = self.system_projects / 'guia-do-docs-local'
        for name, value in (('PROJECTS', self.user_projects), ('SYSTEM_PROJECTS', self.system_projects)):
            patcher = patch.object(project_service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def start_application(self):
        from app import main

        async def start():
            async with main.lifespan(main.app):
                pass

        with (
            patch.object(main, 'REPO', self.root / 'repository'),
            patch.object(main, 'PROJECTS', self.user_projects),
            patch.object(main, 'STATE', self.root / 'state'),
            patch.object(main.instance_lock, 'acquire'),
            patch.object(main.instance_lock, 'release'),
            patch.object(main.sync_manager, 'start'),
            patch.object(main.sync_manager, 'worker', None),
            patch.dict(main.CONFIG['github'], {'enabled': False}),
        ):
            asyncio.run(start())

    def test_system_guide_is_listed_once_without_a_user_copy(self):
        self.start_application()
        self.start_application()
        projects = project_service.list_projects()
        self.assertEqual([item['id'] for item in projects], ['guia-do-docs-local'])
        self.assertTrue(projects[0]['system'])
        self.assertTrue(projects[0]['protected'])
        self.assertFalse((self.user_projects / 'guia-do-docs-local').exists())
        self.assertFalse(any('guia-do-docs-local' in path for path in local_snapshot(self.root / 'repository')))

    def test_manual_changes_are_not_overwritten_and_deleted_files_are_not_recreated(self):
        skill = self.guide / 'skill.md'
        skill.write_text('# My manually edited skill', encoding='utf-8')
        self.start_application()
        self.assertEqual(skill.read_text(encoding='utf-8'), '# My manually edited skill')
        skill.unlink()
        self.start_application()
        self.assertFalse(skill.exists())
        self.assertEqual([doc['path'] for doc in document_service.list_documents('guia-do-docs-local')], ['index.md'])

    def test_read_only_is_enforced_even_if_metadata_is_changed_manually(self):
        metadata = self.guide / 'project.toml'
        metadata.write_text(metadata.read_text(encoding='utf-8').replace('protected = true', 'protected = false'), encoding='utf-8')
        document = document_service.list_documents('guia-do-docs-local')[0]
        with self.assertRaises(AppError):
            document_service.update_document('guia-do-docs-local', document['id'], '# Changed', document['revision'])
        with self.assertRaises(AppError):
            project_service.delete_project('guia-do-docs-local')

    def test_legacy_user_copy_does_not_shadow_or_duplicate_system_guide(self):
        shutil.copytree(self.guide, self.user_projects / 'guia-do-docs-local')
        self.assertEqual(len(project_service.list_projects()), 1)
        self.assertEqual(project_service.get_folder('guia-do-docs-local')[0], self.guide.resolve())
        self.assertEqual(local_snapshot(self.root / 'repository'), {})

    def test_user_project_cannot_take_the_system_id(self):
        project = project_service.create_project('Guia do Docs Local')
        self.assertNotEqual(project['id'], 'guia-do-docs-local')

    def test_all_system_projects_are_listed_and_can_be_opened_alongside_user_projects(self):
        from app.services.toml_writer import dumps_values
        folder = self.system_projects / 'another-system-project'
        folder.mkdir()
        (folder / 'project.toml').write_text(dumps_values({
            'id': folder.name, 'slug': folder.name, 'name': 'Another system project',
            'archived': False,
        }), encoding='utf-8')
        (folder / 'index.md').write_text('# System content', encoding='utf-8')
        user = project_service.create_project('User project')
        listed = {project['id']: project for project in project_service.list_projects()}
        self.assertEqual(set(listed), {'guia-do-docs-local', folder.name, user['id']})
        resolved, metadata = project_service.get_folder(folder.name)
        self.assertEqual(resolved, folder.resolve())
        self.assertTrue(metadata['system'])
        self.assertTrue(metadata['protected'])
        self.assertEqual(document_service.list_documents(folder.name)[0]['path'], 'index.md')
        collision = project_service.create_project('Another system project')
        self.assertNotEqual(collision['id'], folder.name)
