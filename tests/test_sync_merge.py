import unittest

from app.services.sync_merge import blob_sha, merge_snapshots


def document(content, identity='original'):
    return f'<!-- docs-local: id={identity} revision=1 updated=2026-01-01 -->\n{content}'.encode()


class MergeTests(unittest.TestCase):
    def test_fresh_installation_restores_backup_without_deleting_remote_files(self):
        remote = {'projetos/projeto/index.md': document('# Meu projeto'), 'projetos/projeto/docs/a.md': b'backup'}
        self.assertEqual(merge_snapshots({}, remote, {}).files, remote)

    def test_pending_local_additions_are_uploaded_alongside_the_backup(self):
        remote = {'remote.md': b'remote'}
        local = {'local.md': b'local'}
        self.assertEqual(merge_snapshots(local, remote, {}).files, {**local, **remote})

    def test_three_way_merge_preserves_changes_on_both_sides(self):
        baseline = {'a': blob_sha(b'old-a'), 'b': blob_sha(b'old-b')}
        result = merge_snapshots({'a': b'local-a', 'b': b'old-b'}, {'a': b'old-a', 'b': b'remote-b'}, baseline)
        self.assertEqual(result.files, {'a': b'local-a', 'b': b'remote-b'})

    def test_conflicts_preserve_local_content_with_a_distinct_document_id(self):
        path = 'projetos/projeto/docs/a.md'
        local = {path: document('# Local')}
        remote = {path: document('# GitHub')}
        merged = merge_snapshots(local, remote, {path: blob_sha(document('# Antes'))})
        self.assertEqual(merged.files[path], remote[path])
        self.assertEqual(len(merged.conflicts), 1)
        conflict = merged.files[merged.conflicts[0]]
        self.assertIn(b'# Local', conflict)
        self.assertNotIn(b'id=original ', conflict)
        repeated = merge_snapshots(merged.files, remote, {})
        self.assertEqual(repeated.files, merged.files)

    def test_same_document_body_with_different_installation_metadata_is_not_duplicated(self):
        path = 'projetos/guia/index.md'
        remote = {path: document('# Guia', 'remote-id')}
        local = {path: document('# Guia', 'local-id')}
        self.assertEqual(merge_snapshots(local, remote, {}).files, remote)

    def test_explicit_local_deletion_requires_a_baseline_and_preserves_remote_edits(self):
        baseline = {'a': blob_sha(b'old'), 'b': blob_sha(b'old')}
        result = merge_snapshots({}, {'a': b'old', 'b': b'edited'}, baseline)
        self.assertEqual(result.files, {'b': b'edited'})

    def test_remote_deletion_does_not_discard_unsent_local_edits(self):
        result = merge_snapshots({'a': b'edited'}, {}, {'a': blob_sha(b'old')})
        self.assertEqual(result.files, {'a': b'edited'})

    def test_document_id_avoids_duplicates_after_a_remote_rename(self):
        old = 'projetos/p/docs/old.md'
        new = 'projetos/p/docs/new.md'
        before = document('# Before')
        result = merge_snapshots({old: document('# Local edit')}, {new: before}, {old: blob_sha(before)})
        self.assertEqual(result.files, {new: document('# Local edit')})

    def test_pending_local_rename_is_not_undone(self):
        old = 'projetos/p/docs/old.md'
        new = 'projetos/p/docs/new.md'
        content = document('# Content')
        result = merge_snapshots({new: content}, {old: content}, {old: blob_sha(content)})
        self.assertEqual(result.files, {new: content})

    def test_project_timestamps_do_not_create_conflict_copies(self):
        path = 'projetos/p/project.toml'
        common = b'id = "p"\nslug = "p"\nname = "Projeto"\n'
        remote = {path: common + b'created_at = "remote"\nupdated_at = "remote"\n'}
        local = {path: common + b'created_at = "local"\nupdated_at = "local"\n'}
        self.assertEqual(merge_snapshots(local, remote, {}).files, remote)

    def test_existing_file_at_conflict_copy_path_is_preserved(self):
        local_content = document('# Local')
        conflict = f'projetos/p/docs/a.conflito-local-{blob_sha(local_content)[:12]}.md'
        local = {'projetos/p/docs/a.md': local_content, conflict: b'Existing user file'}
        result = merge_snapshots(local, {'projetos/p/docs/a.md': document('# Remote')}, {})
        self.assertEqual(result.files[conflict], b'Existing user file')
        self.assertEqual(len(result.files), 3)
