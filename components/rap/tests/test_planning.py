"""Dependency-free planning checks; model inference is mocked."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_runner(folder):
    config = load_module(folder / 'config.py', 'test_config')
    with patch.dict(sys.modules, {'config': config}):
        name = 'run_ablation.py' if folder.name == 'retrieval_ablation' else 'run_local_model.py'
        return load_module(folder / name, 'test_runner')


class PlanningTests(unittest.TestCase):
    def test_repository_defaults_exist(self):
        config = load_module(ROOT / 'OSWorld/config.py', 'test_config')
        self.assertTrue(Path(config.MANUAL_PATH).is_file())
        self.assertTrue(Path(config.EVALUATION_EXAMPLES_ROOT).is_dir())
        self.assertEqual(Path(config.OUTPUT_ROOT).parent, ROOT / 'OSWorld/outputs')

    def test_ablation_imports_relocated_base(self):
        ablation = load_runner(ROOT / 'OSWorld/retrieval_ablation')
        runner = ablation.load_base_runner()
        self.assertEqual(Path(runner.__file__), ROOT / 'OSWorld/run_local_model.py')

    def test_rank_and_random_retrieval(self):
        runner = load_runner(ROOT / 'OSWorld/retrieval_ablation')
        sections = {i: {'text_full': f'section {i}', 'start_page': i} for i in range(20)}
        store = MagicMock()
        store.similarity_search.return_value = [types.SimpleNamespace(metadata={'section_id': i}) for i in range(10)]
        docs, _ = runner.select_sections('task', store, sections, 'top6_10', 0)
        self.assertEqual(docs, [f'section {i}' for i in range(5, 10)])
        store.similarity_search.assert_called_once_with('task', k=10)
        first = runner.select_sections('task', store, sections, 'random5', 42)
        self.assertEqual(first, runner.select_sections('task', store, sections, 'random5', 42))
        self.assertEqual(len(set(first[0])), 5)
        self.assertNotEqual(first, runner.select_sections('other task', store, sections, 'random5', 42))

    def test_gpu_budget_and_invalid_ids(self):
        runner = load_runner(ROOT / 'OSWorld')
        torch = MagicMock()
        torch.cuda.is_available.return_value = True
        torch.cuda.device_count.return_value = 2
        torch.cuda.mem_get_info.return_value = (8 * 1024**3, 12 * 1024**3)
        with patch.dict(sys.modules, {'torch': torch}):
            self.assertEqual(runner.get_generation_max_memory([0, 1]), {0: 6 * 1024**3, 1: 6 * 1024**3})
            for devices in [[], [0, 0], [-1], [2]]:
                with self.assertRaises(ValueError):
                    runner.get_generation_max_memory(devices)
            torch.cuda.mem_get_info.return_value = (1024**3, 12 * 1024**3)
            with self.assertRaises(RuntimeError):
                runner.get_generation_max_memory([0])

    def test_model_loading_uses_shards_and_rejects_offload(self):
        runner = load_runner(ROOT / 'OSWorld')
        transformers = MagicMock()
        model = transformers.AutoModelForImageTextToText.from_pretrained.return_value
        model.hf_device_map = {'embed': 0, 'layer': 1}
        with patch.dict(sys.modules, {'transformers': transformers}), \
             patch.object(runner, 'get_generation_max_memory', return_value={0: 100, 1: 200}):
            runner.get_rewrite_model([0, 1])
            kwargs = transformers.AutoModelForImageTextToText.from_pretrained.call_args.kwargs
            self.assertEqual(kwargs['device_map'], 'balanced')
            self.assertEqual(kwargs['max_memory'], {0: 100, 1: 200})
            model.hf_device_map = {'layer': 'cpu'}
            with self.assertRaises(RuntimeError):
                runner.get_rewrite_model([0, 1])

    def test_support_files_resolve_from_evaluation_directory(self):
        runner = load_runner(ROOT / 'OSWorld')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'osworld/evaluation_examples'
            source.mkdir(parents=True)
            (source / 'payload.txt').write_text('fixture')
            (source / 'helper.json').write_text(json.dumps({'path': 'evaluation_examples/payload.txt'}))
            output = root / 'planning/outputs/calc'
            runner.copy_support_files({'evaluation_examples/helper.json'}, source, output)
            helper = json.loads((output / 'helper.json').read_text())
            resolved = (source.parent / helper['path']).resolve()
            self.assertEqual(resolved, output / 'payload.txt')
            self.assertEqual(resolved.read_text(), 'fixture')

    def test_output_guard_protects_source_and_existing_outputs(self):
        runner = load_runner(ROOT / 'OSWorld')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'evaluation_examples'
            examples = source / 'examples/libreoffice_calc'
            examples.mkdir(parents=True)
            (examples / 'id.json').write_text('{"id":"id","instruction":"task"}')
            manual = root / 'manual.json'
            manual.write_text('[{"text":"manual"}]')
            output = root / 'output'
            output.mkdir()
            (output / 'keep.txt').write_text('keep')
            with patch.multiple(runner, EVALUATION_EXAMPLES_ROOT=str(source),
                                MANUAL_PATH=str(manual), FIRST_IMAGE_ROOT=str(root/'images'),
                                OUTPUT_ROOT=str(output)), \
                 patch.object(sys, 'argv', ['run_local_model.py']):
                with self.assertRaises(FileExistsError): runner.main()
                self.assertEqual((output / 'keep.txt').read_text(), 'keep')
                runner.OUTPUT_ROOT = str(source)
                with self.assertRaises(ValueError): runner.main()

    def test_precomputed_metadata_resolves_all_tasks(self):
        for meta in (ROOT / 'OSWorld/Plan').glob('*/test_*.json'):
            for domain, ids in json.loads(meta.read_text()).items():
                for task_id in ids:
                    self.assertTrue((meta.parent/'examples'/domain/(task_id+'.json')).is_file(), (meta, task_id))


if __name__ == '__main__':
    unittest.main()
