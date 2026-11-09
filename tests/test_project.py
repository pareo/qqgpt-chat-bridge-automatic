from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
import httpx
import tomlkit

ROOT = Path('/project')
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'plugins'))
import project
from daifeilong import media
from daifeilong.plugin import DaifeilongPlugin, sent_ok


def example(name):
    return project.read_json(ROOT / 'config' / 'examples' / (name + '.json'))


def configured():
    config = example('project')
    config['bot']['account'] = '100001'
    config['groups'] = [{'name': 'test', 'id': '200001'}]
    config['api']['chat_model'] = 'test-model'
    credentials = example('secrets')
    credentials['sub2api_api_key'] = 'test-key-not-real'
    return config, credentials


class ConfigurationTests(unittest.TestCase):
    def test_missing_api_stops_start(self):
        config, credentials = configured()
        credentials['sub2api_api_key'] = ''
        self.assertTrue(project.validate(config, credentials, require_api=True))
        self.assertEqual(project.validate(config, credentials, require_api=False), [])

    def test_no_group_or_duplicate_ids_rejected(self):
        config, credentials = configured()
        config['groups'] = []
        self.assertTrue(project.validate(config, credentials, require_api=True))
        config['groups'] = [{'name': 'a', 'id': '1'}, {'name': 'b', 'id': '1'}]
        self.assertTrue(project.validate(config, credentials, require_api=True))

    def test_policy_defaults_block_and_only_allow_origin_account(self):
        config, credentials = configured()
        docs = project.make_documents(config, credentials, example('modes'), {})
        policy = docs['policy']
        self.assertEqual(policy['defaults']['group']['default_action'], 'block')
        self.assertEqual(policy['defaults']['private']['default_action'], 'block')
        self.assertEqual(policy['adapters'][0]['account_id'], '100001')
        self.assertEqual(policy['adapters'][0]['group']['allow_ids'], ['200001'])

    def test_documents_round_trip_without_losing_persona(self):
        config, credentials = configured()
        modes = example('modes')
        modes['大肥龙模式'] = '白发小龙娘\n保留完整口癖及示例「我超」'
        docs = project.make_documents(config, credentials, modes, {})
        for name in ('bot', 'model', 'policy', 'connector'):
            parsed = tomlkit.parse(tomlkit.dumps(docs[name])).unwrap()
            self.assertEqual(parsed, docs[name])
        self.assertEqual(docs['bot']['personality']['personality'], modes['大肥龙模式'])
        self.assertEqual(docs['bot']['files']['max_file_mib'], 10)
        self.assertFalse(docs['bot']['emoji']['steal_emoji'])

    def test_all_groups_option_still_blocks_other_accounts_and_private(self):
        config, credentials = configured()
        config['bot']['listen_mode'] = 'all'
        docs = project.make_documents(config, credentials, example('modes'), {})
        self.assertEqual(docs['policy']['adapters'][0]['group']['default_action'], 'allow')
        self.assertEqual(docs['policy']['defaults']['group']['default_action'], 'block')
        self.assertEqual(docs['policy']['adapters'][0]['private']['default_action'], 'block')

    def test_runtime_configs_validate_with_real_maibot(self):
        os.environ['MAIBOT_INITIALIZE_ONLY'] = '1'
        from src.config.config import Config, ModelConfig
        from src.config.config_base import AttributeData
        config, credentials = configured()
        docs = project.make_documents(config, credentials, example('modes'), {})
        bot_doc, model_doc = copy.deepcopy(docs['bot']), copy.deepcopy(docs['model'])
        bot_doc.pop('inner')
        model_doc.pop('inner')
        bot = Config.from_dict(AttributeData(), bot_doc)
        model = ModelConfig.from_dict(AttributeData(), model_doc)
        self.assertEqual(bot.files.max_file_mib, 10)
        self.assertEqual(model.models[0].extra_params['reasoning']['effort'], 'medium')

    def test_chat_completions_keeps_top_level_reasoning_effort(self):
        config, credentials = configured()
        config['api']['client_type'] = 'openai'
        docs = project.make_documents(config, credentials, example('modes'), {})
        self.assertEqual(docs['model']['models'][0]['extra_params'], {'reasoning_effort': 'medium'})


class MediaTests(unittest.TestCase):
    def test_image_failure_preserves_reason_and_redacts_key(self):
        config, credentials = configured()
        config['images'].update(enabled=True, model='test-image-model')
        def handle(request):
            return httpx.Response(404, json={'error': {'message': 'model unavailable ' + credentials['sub2api_api_key']}})
        client_class = httpx.Client
        with patch('daifeilong.media.read_settings', return_value=(config, credentials, {})), patch('daifeilong.media.httpx.Client', side_effect=lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)):
            with self.assertRaises(media.ImageError) as caught:
                media.generate(Path('.'), '城堡', 'image', '')
        self.assertIn('model unavailable', str(caught.exception))
        self.assertNotIn(credentials['sub2api_api_key'], str(caught.exception))

    def test_real_http_client_parses_base64_generation(self):
        config, credentials = configured()
        config['images'].update(enabled=True, model='test-image-model')
        picture = io.BytesIO()
        Image.new('RGB', (32, 20), 'blue').save(picture, 'PNG')
        raw = picture.getvalue()
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(raw).decode()}]})
        client_class = httpx.Client
        with patch('daifeilong.media.read_settings', return_value=(config, credentials, {})), patch('daifeilong.media.httpx.Client', side_effect=lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)):
            actual = media.generate(Path('.'), '画城堡', 'image', '')
        self.assertEqual(actual, raw)
        self.assertEqual(len(calls), 1)
        self.assertTrue(str(calls[0].url).endswith('/images/generations'))
        self.assertEqual(json.loads(calls[0].content)['quality'], 'high')

    def test_edit_sends_original_to_edits_endpoint(self):
        config, credentials = configured()
        config['images'].update(enabled=True, model='test-image-model')
        picture = io.BytesIO()
        Image.new('RGB', (32, 20), 'blue').save(picture, 'PNG')
        raw = picture.getvalue()
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(raw).decode()}]})
        client_class = httpx.Client
        with patch('daifeilong.media.read_settings', return_value=(config, credentials, {})), patch('daifeilong.media.httpx.Client', side_effect=lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)):
            media.generate(Path('.'), '改成下雨', 'image', '', [('original.png', raw)])
        self.assertTrue(str(calls[0].url).endswith('/images/edits'))
        self.assertIn(b'original.png', calls[0].content)
        self.assertIn(raw, calls[0].content)

    def test_sticker_size_dpi_and_no_crop(self):
        data = io.BytesIO()
        Image.new('RGB', (900, 500), 'red').save(data, 'PNG')
        result = Image.open(io.BytesIO(media.sticker_png(data.getvalue())))
        self.assertEqual(result.size, (300, 300))
        self.assertAlmostEqual(result.info['dpi'][0], 96, delta=.1)
        self.assertEqual(result.getpixel((0, 0))[3], 0)

    def test_table_escaped_pipe_and_html_are_preserved(self):
        html = media.table_html('|标题|值|\n|---|---|\n|a\\|b|<script>x</script>|')
        self.assertIn('a|b', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)

    def test_inconsistent_columns_rejected(self):
        with self.assertRaises(ValueError):
            media.table_html('|a|b|\n|---|---|\n|x|y|z|')

    def test_reference_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(media.ImageError):
                media.reference_files(Path(folder), {'gpt': {'reference': '../secret.png'}}, 'gpt')

    def test_success_requires_confirmation(self):
        self.assertFalse(sent_ok({'message_id': '123'}))
        self.assertFalse(sent_ok(False))
        self.assertTrue(sent_ok({'sent': True, 'message_id': '123'}))


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from types import SimpleNamespace
        self.plugin = DaifeilongPlugin()
        self.plugin.set_plugin_config({})
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        self.plugin._set_context(SimpleNamespace(
            send=SimpleNamespace(text=AsyncMock(return_value=True), image=AsyncMock(return_value={'sent': True, 'message_id': 'test'})),
            personality=SimpleNamespace(list=AsyncMock(return_value={'profiles': [{'name': '大肥龙模式'}, {'name': '正经模式'}]}), switch=AsyncMock(), get_current=AsyncMock(return_value={'name': '大肥龙模式'})),
            logger=SimpleNamespace(info=lambda *a: None, error=lambda *a: None),
            paths=SimpleNamespace(data_dir=Path(self.cache.name)),
            maisaka=SimpleNamespace(context=SimpleNamespace(resolve_image=AsyncMock())),
        ))
        await self.plugin.on_load()

    async def test_mode_switch_uses_runner_named_capture(self):
        await self.plugin.switch_mode(stream_id='origin', matched_groups={'mode': '正经模式'})
        self.plugin.ctx.personality.switch.assert_awaited_once_with('正经模式')
        self.plugin.ctx.send.text.assert_awaited_once_with('已切换到正经模式', 'origin')

    async def test_disabled_casual_images_do_not_report_errors_to_group(self):
        config, credentials = configured()
        config['images']['enabled'] = False
        with patch('daifeilong.plugin.read_settings', return_value=(config, credentials, {})), patch('daifeilong.plugin.generate') as generate:
            result = await self.plugin.generate_image('笑', kind='casual_sticker', stream_id='origin')
        self.assertTrue(result['skipped'])
        generate.assert_not_called()
        self.plugin.ctx.send.text.assert_not_awaited()

    async def test_explicit_image_bypasses_casual_probability(self):
        config, credentials = configured()
        config['images']['casual_probability'] = 0
        with patch('daifeilong.plugin.read_settings', return_value=(config, credentials, {})), patch('daifeilong.plugin.generate', return_value=b'pretend-generated-image') as generate:
            result = await self.plugin.generate_image('画一座城堡', kind='image', stream_id='origin')
        generate.assert_called_once()
        self.assertTrue(result['sent'])
        self.assertEqual(self.plugin.ctx.send.image.call_args.args[1], 'origin')

    async def test_zero_probability_only_skips_casual_image(self):
        config, credentials = configured()
        config['images']['casual_probability'] = 0
        self.plugin.set_plugin_config({'plugin': {'config_version': '1.0.0'}, 'reactions': {'probability': 0}})
        with patch('daifeilong.plugin.read_settings', return_value=(config, credentials, {})), patch('daifeilong.plugin.generate') as generate:
            result = await self.plugin.generate_image('笑', kind='casual_sticker', stream_id='origin')
        generate.assert_not_called()
        self.assertTrue(result['skipped'])

    async def test_failed_delivery_does_not_repeat_generation(self):
        config, credentials = configured()
        self.plugin.ctx.send.image.return_value = {'sent': False}
        with patch('daifeilong.plugin.read_settings', return_value=(config, credentials, {})), patch('daifeilong.plugin.generate', return_value=b'image') as generate:
            result = await self.plugin.generate_image('城堡', kind='image', stream_id='origin')
        self.assertFalse(result['success'])
        generate.assert_called_once()
        self.plugin.ctx.send.image.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
