from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from runtime_guard import repair_usage_file
from runtime_status import summarize_plugins


class RuntimeGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'plugin_usage.json'

    def test_missing_and_valid_usage_are_unchanged(self):
        self.assertIsNone(repair_usage_file(self.path))
        original = b'{"version":1,"usage_seconds":{"qq-connector":123.5}}\n'
        self.path.write_bytes(original)
        self.assertIsNone(repair_usage_file(self.path))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_corrupt_records_are_archived_without_touching_other_files(self):
        history = self.path.parent / 'MaiBot.db'
        history.write_bytes(b'unchanged chat history')
        for raw in (b'\x00' * 169, b'', b'{"version":1', b'\xff\xfe', b'[]', b'{"version":1,"usage_seconds":{"a":true}}', b'{"version":1,"usage_seconds":{"a":-1}}', b'{"version":1,"usage_seconds":{"a":NaN}}'):
            with self.subTest(raw=raw[:30]):
                self.path.write_bytes(raw)
                backup = repair_usage_file(self.path)
                self.assertEqual(backup.read_bytes(), raw)
                self.assertEqual(json.loads(self.path.read_text()), {'version': 1, 'usage_seconds': {}})
                self.assertIsNone(repair_usage_file(self.path))
                self.assertEqual(history.read_bytes(), b'unchanged chat history')

    def test_failed_replacement_restores_original_corrupt_bytes(self):
        raw = b'\x00' * 169
        self.path.write_bytes(raw)
        with patch('runtime_guard.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                repair_usage_file(self.path)
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_running_host_does_not_mask_missing_or_failed_plugins(self):
        for plugins in ([], [{'id': 'qq', 'load_status': 'failed', 'loaded': False}], [{'id': 'qq', 'load_status': 'success', 'loaded': False}]):
            with self.subTest(plugins=plugins):
                self.assertFalse(summarize_plugins({'success': True, 'plugins': plugins}, ['qq'])['plugins_ready'])
        healthy = [{'id': 'qq', 'load_status': 'success', 'loaded': True}]
        self.assertTrue(summarize_plugins({'success': True, 'plugins': healthy}, ['qq'])['plugins_ready'])
        with self.assertRaises(ValueError):
            summarize_plugins({'success': False, 'plugins': healthy}, ['qq'])
