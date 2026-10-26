import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.core.exceptions import AppError
from app.services import document_service as documents
from app.services import project_service as projects
from app.services import search_service as search
from app.services import git_service


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.projects_root = Path(self.temporary_folder.name) / 'projetos'
        self.projects_root.mkdir()
        self.project_root_patch = patch.object(projects, 'PROJECTS', self.projects_root)
        self.project_root_patch.start()
        system_patch = patch.object(projects, 'SYSTEM_PROJECTS', self.projects_root.parent / 'system-projects')
        system_patch.start()
        self.addCleanup(system_patch.stop)

    def tearDown(self):
        self.project_root_patch.stop()
        self.temporary_folder.cleanup()

    def test_create_and_list_projects(self):
        first_project = projects.create_project('Árvore do saber', 'Notas')
        second_project = projects.create_project('Árvore do saber')

        self.assertNotEqual(first_project['id'], second_project['id'])
        self.assertEqual(len(projects.list_projects()), 2)
        self.assertTrue((self.projects_root / first_project['id'] / 'index.md').is_file())

    def test_tree_lists_empty_folders_and_markdown_moved_outside_docs(self):
        project = projects.create_project('Filesystem')
        folder = self.projects_root / project['id']
        (folder / 'abc' / 'empty').mkdir(parents=True)
        document = documents.create_document(project['id'], 'docs/skill.md', content='# Skill')
        (folder / 'docs/skill.md').rename(folder / 'skill.md')
        tree = {node['name']: node for node in documents.tree(project['id'])}
        self.assertEqual(tree['docs']['children'], [])
        self.assertEqual(tree['abc']['children'][0]['name'], 'empty')
        self.assertEqual(tree['abc']['children'][0]['children'], [])
        self.assertEqual(tree['skill.md']['path'], 'skill.md')
        self.assertEqual(documents.read_document(project['id'], document['id'])['path'], 'skill.md')
        self.assertEqual(projects.list_projects()[0]['document_count'], 2)

    def test_markdown_and_folders_can_be_created_outside_docs(self):
        project = projects.create_project('Any folder')
        documents.create_folder(project['id'], 'abc/empty')
        document = documents.create_document(project['id'], 'abc/note.md', content='# Note')
        moved = documents.update_document(project['id'], document['id'], '# Note', 1, 'note.md')
        self.assertEqual(moved['path'], 'note.md')

    def test_create_update_and_reject_stale_document_revision(self):
        project = projects.create_project('Projeto')
        document = documents.create_document(
            project['id'],
            'docs/nota.md',
            'Nota',
            '# Nota\ntexto',
        )
        updated = documents.update_document(
            project['id'], document['id'], '# Novo\n', expected_revision=1
        )

        self.assertEqual(updated['revision'], 2)
        self.assertEqual(documents.read_document(project['id'], document['id'])['content'], '# Novo\n')
        with self.assertRaises(AppError) as error:
            documents.update_document(
                project['id'], document['id'], 'conteúdo perdido', expected_revision=1
            )
        self.assertEqual(error.exception.status, 409)

    def test_projects_cannot_read_each_others_documents(self):
        first_project = projects.create_project('Um')
        second_project = projects.create_project('Dois')
        document = documents.create_document(
            first_project['id'], 'docs/segredo.md', 'Segredo', 'conteúdo especial'
        )

        matches = search.search('especial', first_project['id'])
        self.assertEqual(matches[0]['project_id'], first_project['id'])
        self.assertEqual(search.search('especial', second_project['id']), [])
        with self.assertRaises(AppError):
            documents.read_document(second_project['id'], document['id'])

    def test_path_traversal_is_rejected(self):
        project = projects.create_project('Seguro')
        with self.assertRaises(AppError):
            documents.create_document(project['id'], '../../outside.md')

    def test_move_preserves_document_identity(self):
        project = projects.create_project('Mover')
        document = documents.create_document(project['id'], 'docs/a.md', 'A', 'A')
        moved = documents.update_document(
            project['id'],
            document['id'],
            'B',
            expected_revision=1,
            new_path='docs/sub/b.md',
        )

        self.assertEqual(moved['id'], document['id'])
        self.assertTrue((self.projects_root / project['id'] / 'docs/sub/b.md').exists())

    def test_concurrent_stale_writes_cannot_overwrite_each_other(self):
        from concurrent.futures import ThreadPoolExecutor

        project = projects.create_project('Concorrência')
        document = documents.create_document(
            project['id'], 'docs/arquivo.md', 'Arquivo', 'inicial'
        )

        def save(content):
            try:
                return documents.update_document(
                    project['id'],
                    document['id'],
                    content,
                    expected_revision=1,
                )
            except AppError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['versão A', 'versão B']))

        successful_saves = [result for result in results if not isinstance(result, AppError)]
        rejected_saves = [result for result in results if isinstance(result, AppError)]
        self.assertEqual(len(successful_saves), 1)
        self.assertEqual(len(rejected_saves), 1)
        self.assertEqual(documents.read_document(project['id'], document['id'])['revision'], 2)

    def test_archiving_preserves_and_can_restore_project(self):
        project = projects.create_project('Guardar')
        projects.delete_project(project['id'])

        self.assertEqual(projects.list_projects(), [])
        self.assertTrue((self.projects_root / project['id'] / 'index.md').exists())
        restored = projects.update_project(project['id'], {'archived': False})
        self.assertFalse(restored['archived'])


class GitTests(unittest.TestCase):
    def run_git(self, *arguments, cwd=None, check=True):
        return subprocess.run(
            ['git', *arguments],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_git_subprocesses_do_not_open_console_windows(self):
        class CompletedGitProcess:
            returncode = 0

            async def communicate(self):
                return b'', b''

        process_launcher = AsyncMock(return_value=CompletedGitProcess())
        service = git_service.GitSync()
        with patch.object(
            git_service.asyncio,
            'create_subprocess_exec',
            process_launcher,
        ):
            asyncio.run(service._run_git('status', '--porcelain'))

        self.assertEqual(
            process_launcher.await_args.kwargs['creationflags'],
            git_service.GIT_PROCESS_CREATION_FLAGS,
        )

        completed_command = subprocess.CompletedProcess(['git', 'log'], 0, '')
        with patch.object(
            git_service.subprocess,
            'run',
            return_value=completed_command,
        ) as run_git:
            git_service.GitSync._read_history(['git', 'log'])

        self.assertEqual(
            run_git.call_args.kwargs['creationflags'],
            git_service.GIT_PROCESS_CREATION_FLAGS,
        )

    def test_git_commit_and_clean_worktree_without_github(self):
        try:
            self.run_git('--version')
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.skipTest('Git CLI indisponível')

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            repository = root / 'repository'
            repository.mkdir()
            self.run_git('init', '-b', 'main', cwd=repository)
            self.run_git('config', 'user.name', 'Docs Local Test', cwd=repository)
            self.run_git('config', 'user.email', 'docs-local@example.invalid', cwd=repository)
            self.run_git('config', 'commit.gpgsign', 'false', cwd=repository)
            (repository / 'doc.md').write_text('# teste', encoding='utf-8')

            self.run_git('add', '-A', cwd=repository)
            self.run_git('commit', '-m', 'docs: teste', cwd=repository)
            first_commit = self.run_git('rev-parse', 'HEAD', cwd=repository).stdout

            self.assertEqual(self.run_git('status', '--porcelain', cwd=repository).stdout, '')
            second_commit = self.run_git('rev-parse', 'HEAD', cwd=repository).stdout
            self.assertEqual(first_commit, second_commit)
            restored_content = self.run_git('show', 'HEAD:doc.md', cwd=repository).stdout
            self.assertEqual(restored_content, '# teste')

    def test_sync_service_commits_local_changes_and_skips_empty_commits(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            repository = root / 'repository'
            state_folder = root / 'state'
            repository.mkdir()
            self.run_git('init', '-b', 'main', cwd=repository)
            self.run_git('config', 'user.name', 'Docs Local Test', cwd=repository)
            self.run_git('config', 'user.email', 'docs-local@example.invalid', cwd=repository)
            self.run_git('config', 'commit.gpgsign', 'false', cwd=repository)
            (repository / 'doc.md').write_text('# sync manager', encoding='utf-8')

            with (
                patch.object(git_service, 'REPO', repository),
                patch.object(git_service, 'STATE', state_folder),
                patch.object(git_service, 'STATUS_FILE', state_folder / 'sync.json'),
                patch.dict(
                    git_service.CONFIG['git'],
                    {'enabled': True, 'remote': 'origin', 'branch': 'main'},
                ),
            ):
                service = git_service.GitSync()
                pushed_branches = []

                async def run_git_without_async_io(*arguments):
                    if arguments[0] == 'push':
                        pushed_branches.append(arguments[-1])
                        return 0, '', ''
                    if arguments[:2] == ('remote', 'get-url'):
                        return 0, 'https://example.invalid/docs.git', ''
                    result = self.run_git(*arguments, cwd=repository, check=False)
                    return result.returncode, result.stdout, result.stderr

                service._run_git = run_git_without_async_io
                self._run_immediate_coroutine(service._sync_once())
                first_commit = self.run_git('rev-parse', 'HEAD', cwd=repository).stdout
                self._run_immediate_coroutine(service._sync_once())
                second_commit = self.run_git('rev-parse', 'HEAD', cwd=repository).stdout

                self.assertEqual(service.status['state'], 'synced')
                self.assertEqual(first_commit, second_commit)
                self.assertEqual(pushed_branches, ['HEAD:main', 'HEAD:main'])

    def test_sync_failure_keeps_the_local_commit_pending_for_recovery(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            repository = root / 'repository'
            state_folder = root / 'state'
            repository.mkdir()
            self.run_git('init', '-b', 'main', cwd=repository)
            self.run_git('config', 'user.name', 'Docs Local Test', cwd=repository)
            self.run_git('config', 'user.email', 'docs-local@example.invalid', cwd=repository)
            self.run_git('config', 'commit.gpgsign', 'false', cwd=repository)
            (repository / 'doc.md').write_text('# preservado localmente', encoding='utf-8')

            with (
                patch.object(git_service, 'REPO', repository),
                patch.object(git_service, 'STATE', state_folder),
                patch.object(git_service, 'STATUS_FILE', state_folder / 'sync.json'),
                patch.dict(
                    git_service.CONFIG['git'],
                    {'enabled': True, 'remote': 'origin', 'branch': 'main'},
                ),
            ):
                service = git_service.GitSync()

                async def run_git_without_async_io(*arguments):
                    if arguments[:2] == ('remote', 'get-url'):
                        return 2, '', "fatal: 'origin' does not appear to be a git repository"
                    result = self.run_git(*arguments, cwd=repository, check=False)
                    return result.returncode, result.stdout, result.stderr

                service._run_git = run_git_without_async_io
                self._run_immediate_coroutine(service._sync_once())

                commit = self.run_git('log', '-1', '--format=%s', cwd=repository).stdout
                self.assertTrue(commit.startswith('docs:'))
                self.assertEqual(service.status['state'], 'error')
                self.assertTrue(service.status['pending'])
                self.assertTrue((repository / 'doc.md').exists())

                recovered_service = git_service.GitSync()
                self.assertTrue(recovered_service.status['pending'])

    def test_missing_remote_stops_pending_state_and_automatic_retries(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            repository = root / 'repository'
            state_folder = root / 'state'
            repository.mkdir()
            self.run_git('init', '-b', 'main', cwd=repository)

            with (
                patch.object(git_service, 'REPO', repository),
                patch.object(git_service, 'STATE', state_folder),
                patch.object(git_service, 'STATUS_FILE', state_folder / 'sync.json'),
                patch.dict(
                    git_service.CONFIG['git'],
                    {'enabled': True, 'remote': 'origin', 'branch': 'main'},
                ),
            ):
                service = git_service.GitSync()

                async def run_git_without_async_io(*arguments):
                    if arguments[:2] == ('remote', 'get-url'):
                        return 2, '', "error: No such remote 'origin'"
                    result = self.run_git(*arguments, cwd=repository, check=False)
                    return result.returncode, result.stdout, result.stderr

                service._run_git = run_git_without_async_io
                self._run_immediate_coroutine(service._sync_once())

                self.assertEqual(service.status['state'], 'error')
                self.assertFalse(service.status['pending'])
                self.assertTrue(service.requires_remote_configuration())

    def _run_immediate_coroutine(self, coroutine):
        try:
            coroutine.send(None)
        except StopIteration:
            return
        coroutine.close()
        self.fail('The test double unexpectedly yielded asynchronous I/O.')


if __name__ == '__main__':
    unittest.main()
