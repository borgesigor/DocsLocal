import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class FrozenUserIsolationTests(unittest.TestCase):
    def test_fresh_windows_profiles_have_independent_empty_configuration(self):
        source = Path(__file__).parents[1] / 'app' / 'core' / 'config.py'
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            base = Path(folder)
            configs = []
            for user in ('alice', 'bob'):
                local_appdata = base / user / 'AppData' / 'Local'
                spec = importlib.util.spec_from_file_location(f'isolated_config_{user}', source)
                module = importlib.util.module_from_spec(spec)
                with (
                    patch.object(sys, 'frozen', True, create=True),
                    patch.object(sys, 'executable', str(base / 'software' / 'DocsLocal.exe')),
                    patch.dict(os.environ, {'LOCALAPPDATA': str(local_appdata)}),
                ):
                    spec.loader.exec_module(module)
                self.assertEqual(module.DATA, local_appdata / 'DocsLocal')
                self.assertEqual(module.REPO, (module.DATA / 'repository').resolve())
                self.assertNotIn('client_id', module.CONFIG['github'])
                self.assertFalse((module.STATE / 'github-secrets.bin').exists())
                self.assertFalse(module.PROJECTS.exists())
                configs.append(module)
            self.assertNotEqual(configs[0].REPO, configs[1].REPO)
            self.assertNotEqual(configs[0].STATE, configs[1].STATE)
