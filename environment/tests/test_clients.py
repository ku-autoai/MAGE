"""Desktop-free checks: python3.10 -m unittest discover -s environment/tests."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_client(folder):
    path = ROOT / folder / 'LAM_data_generator'
    mocks = {
        'pyautogui': types.ModuleType('pyautogui'),
        'pipeline': types.ModuleType('pipeline'),
        'pipeline.aci_de': types.ModuleType('pipeline.aci_de'),
        'pipeline.util': types.ModuleType('pipeline.util'),
        'pipeline.util.socket_session': types.ModuleType('pipeline.util.socket_session'),
    }
    mocks['pipeline.aci_de'].OSWorldACI = MagicMock()
    mocks['pipeline.util.socket_session'].SocketSession = MagicMock()
    spec = importlib.util.spec_from_file_location(folder + '_client', path / 'env_desktop.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, mocks):
        spec.loader.exec_module(module)
    return module


class ClientTests(unittest.TestCase):
    def test_vscode_reset_restores_seed_and_preserves_disabled_scope(self):
        client = load_client('docker_vscode')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, attr in [('workspace', 'WORKSPACE_DIR'), ('config', 'CONFIG_DIR'),
                               ('extensions', 'EXTENSIONS_DIR'), ('seed', 'WORKSPACE_SEED_DIR')]:
                folder = root / name
                folder.mkdir()
                (folder / 'old.txt').write_text(name)
                setattr(client, attr, folder)
            (client.WORKSPACE_SEED_DIR / 'project.py').write_text('print("example")')
            with patch.dict(os.environ, {'VSCODE_RESET_CONFIG_ON_EX': 'false',
                                         'VSCODE_RESET_EXTENSIONS_ON_EX': 'true',
                                         'VSCODE_RESET_WORKSPACE_ON_EX': 'true'}), \
                 patch.object(client, '_stop_vscode', return_value={}), \
                 patch.object(client, '_start_vscode') as start:
                client.reset_vscode(relaunch=False)
            start.assert_not_called()
            self.assertEqual((client.CONFIG_DIR / 'old.txt').read_text(), 'config')
            self.assertEqual(list(client.EXTENSIONS_DIR.iterdir()), [])
            self.assertEqual((client.WORKSPACE_DIR / 'old.txt').read_text(), 'seed')
            self.assertTrue((client.WORKSPACE_DIR / 'project.py').is_file())

    def test_vscode_reset_rejects_symlink_and_unapproved_path(self):
        client = load_client('docker_vscode')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'outside'
            outside.mkdir()
            (outside / 'keep.txt').write_text('keep')
            linked = root / 'workspace'
            linked.symlink_to(outside, target_is_directory=True)
            client.WORKSPACE_DIR = linked
            with self.assertRaises(ValueError):
                client._clear_directory(linked)
            with self.assertRaises(ValueError):
                client._clear_directory(outside)
            self.assertEqual((outside / 'keep.txt').read_text(), 'keep')

    def test_gimp_setup_copies_input_and_handles_missing_file(self):
        client = load_client('docker_gimp')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            (source / 'sample_00.png').write_bytes(b'example-image')
            client.SETUP_FILE_PATH = str(source)
            client.SETUP_FILE_EXTENSION = 'png'
            client.WORK_DIR = str(root / 'work')
            with patch.object(client.subprocess, 'Popen') as launch, \
                 patch.object(client.time, 'sleep'):
                self.assertEqual(client.setup_to_train_analysis(0), 'SUCCESS')
                launch.assert_called_once_with(['gimp', str(root / 'work/sample_00.png')])
                self.assertEqual(client.setup_to_train_analysis(1), 'FAIL')
            self.assertEqual((root / 'work/sample_00.png').read_bytes(), b'example-image')
            self.assertEqual((source / 'sample_00.png').read_bytes(), b'example-image')

    def test_slack_setup_launches_slack_and_reports_failure(self):
        client = load_client('docker_slack')
        with patch.object(client.subprocess, 'Popen') as launch:
            self.assertEqual(client.setup_to_train_analysis(0), 'SUCCESS')
            self.assertEqual(launch.call_args.args[0], ['slack'])
            launch.side_effect = FileNotFoundError('slack unavailable')
            self.assertEqual(client.setup_to_train_analysis(1), 'FAIL')


if __name__ == '__main__':
    unittest.main()
