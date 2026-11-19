import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugins'))
from daifeilong import desktop
from daifeilong.plugin import CASUAL_REACTION_POLICY, DaifeilongPlugin, PERSONA_VOICE


def picture():
    output = io.BytesIO()
    Image.new('RGB', (480, 360), 'blue').save(output, 'PNG')
    return output.getvalue()


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_worker_uses_own_url_and_token(self):
        config = {'agent_worker': {'enabled': True, 'url': 'http://codex-worker:18121'}, 'desktop_worker': {'enabled': False}}
        credentials = {'agent_worker_token': 'isolated-test-token-' * 3, 'desktop_worker_token': 'wrong-gui-token-' * 3}
        def handler(request):
            self.assertEqual(request.url.host, 'codex-worker')
            self.assertEqual(request.headers['Authorization'], 'Bearer ' + credentials['agent_worker_token'])
            task = json.loads(request.content)
            return httpx.Response(202, json={'id': task['id'], 'state': 'succeeded', 'result': {'text': 'Codex reply', 'artifacts': []}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await desktop.run_task(config, credentials, 'chat', 'test', client=client)
        self.assertEqual(result['text'], 'Codex reply')

    def settings(self):
        return {'desktop_worker': {'enabled': True, 'url': 'http://worker:18120', 'timeout_seconds': 30}}, {'desktop_worker_token': 'test-token-not-real-' * 3}

    async def test_task_artifact_integrity_and_no_paths_from_response(self):
        config, credentials = self.settings()
        raw, posts = picture(), []
        def handler(request):
            if request.method == 'POST':
                posts.append(json.loads(request.content))
                return httpx.Response(202, json={'state': 'queued'})
            if '/artifacts/' in request.url.path:
                return httpx.Response(200, content=raw)
            return httpx.Response(200, json={'id': posts[0]['id'], 'state': 'succeeded', 'result': {'text': 'done', 'artifacts': [{'id': 'abcdef12', 'kind': 'image', 'name': 'image.png', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await desktop.run_task(config, credentials, 'image', 'draw', client=client, poll_seconds=0)
        self.assertEqual(result['artifacts'][0]['raw'], raw)
        self.assertEqual(len(posts), 1)

    async def test_lost_post_response_never_resubmits(self):
        config, credentials = self.settings()
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout('lost', request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(desktop.DesktopError):
                await desktop.run_task(config, credentials, 'search', 'latest', client=client, poll_seconds=0)
        self.assertEqual(len(calls), 1)

    async def test_uncertain_job_is_not_reasked_or_downloaded(self):
        config, credentials = self.settings()
        payloads, calls = [], []
        def handler(request):
            calls.append(request)
            if request.method == 'POST':
                payloads.append(json.loads(request.content))
                return httpx.Response(202, json={'state': 'queued'})
            return httpx.Response(200, json={'state': 'uncertain', 'id': payloads[0]['id']})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(desktop.DesktopError):
                await desktop.run_task(config, credentials, 'search', 'test', client=client, poll_seconds=0)
        self.assertEqual([r.method for r in calls], ['POST', 'GET'])

    async def test_corrupt_artifact_is_rejected(self):
        config, credentials = self.settings()
        accepted = {}
        def handler(request):
            if request.method == 'POST':
                accepted.update(json.loads(request.content))
                return httpx.Response(202, json={'state': 'queued'})
            if '/artifacts/' in request.url.path:
                return httpx.Response(200, content=b'bad')
            return httpx.Response(200, json={'id': accepted['id'], 'state': 'succeeded', 'result': {'artifacts': [{'id': 'abcd', 'kind': 'file', 'name': 'a.txt', 'bytes': 3, 'sha256': 'wrong'}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(desktop.DesktopError, '校验'):
                await desktop.run_task(config, credentials, 'search', 'test', client=client, poll_seconds=0)


class HybridRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_policy_covers_private_group_and_modes_without_overwriting(self):
        from daifeilong.search_result import apply_reply_policy, SEARCH_REPLY_RULE
        bot = {'chat': {'reply_style': {'private_chat_prompts': '私人说明', 'group_chat_prompt': '群说明'}}, 'personality': {'personality': '保留人设', 'profiles': [{'name': 'a', 'personality': '模式人设', 'private_chat_prompts': ''}]}}
        self.assertEqual(apply_reply_policy(bot), 4)
        self.assertTrue(bot['chat']['reply_style']['private_chat_prompts'].startswith('私人说明'))
        self.assertIn(SEARCH_REPLY_RULE, bot['personality']['profiles'][0]['private_chat_prompts'])
        self.assertEqual(bot['personality']['profiles'][0]['personality'], '模式人设')
        self.assertEqual(bot['personality']['personality'], '保留人设')
        self.assertEqual(apply_reply_policy(bot), 0)

    async def test_blocked_original_keeps_mirror_evidence_and_uncertainty(self):
        from daifeilong.search_result import search_content
        raw = '第三方镜像称：待核实的消息。https://example.com/mirror\n原站403，原帖未直接核验。'
        content = search_content(raw)
        self.assertIn(raw, content)
        self.assertIn('不代表没有检索结果', content)
        self.assertIn('不补写未查到的事实', content)

    async def asyncSetUp(self):
        self.cache = tempfile.TemporaryDirectory()
        self.addCleanup(self.cache.cleanup)
        self.plugin = DaifeilongPlugin()
        self.plugin.set_plugin_config({})
        self.plugin._set_context(SimpleNamespace(
            paths=SimpleNamespace(data_dir=Path(self.cache.name)),
            logger=SimpleNamespace(info=lambda *a: None, error=lambda *a: None),
            send=SimpleNamespace(image=AsyncMock(return_value={'sent': True}), text=AsyncMock(return_value=True)),
            personality=SimpleNamespace(get_current=AsyncMock(return_value={
                'name': '猫娘模式', 'personality': '俏皮地接话', 'reply_style': '自然使用喵',
            })),
            llm=SimpleNamespace(generate=AsyncMock(return_value={'success': True, 'response': '喵，这幅画拿去挂墙上！'})),
        ))
        await self.plugin.on_load()

    async def test_ordinary_reply_preserves_existing_prompt_and_applies_persona_voice(self):
        for message_id in ('123', ''):
            with self.subTest(message_id=message_id):
                result = await self.plugin.supply_current_tool_evidence(
                    session_id='origin', reply_message_id=message_id, extra_prompt='回答简短一些',
                    reply_tool_args={'msg_id': message_id}, model_name='reply-model',
                )
                self.assertEqual(result['modified_kwargs']['extra_prompt'], '回答简短一些\n\n' + PERSONA_VOICE)
                self.assertEqual(result['modified_kwargs']['reply_tool_args'], {'msg_id': message_id})
                self.assertEqual(result['modified_kwargs']['model_name'], 'reply-model')
        self.plugin.ctx.llm.generate.assert_not_awaited()

    async def test_reaction_planner_hint_applies_only_when_tool_and_probability_are_available(self):
        from src.llm_models.payload_content.context_item import CONTEXT_ITEM_SCHEMA_VERSION, ContextItemBuilder, RoleType
        from src.plugin_runtime.hook_payloads import deserialize_prompt_items, serialize_prompt_items

        original = [ContextItemBuilder().set_role(RoleType.System).add_text_content('原提示').build()]
        items = serialize_prompt_items(original)
        definitions = [{'type': 'function', 'function': {'name': 'reply', 'parameters': {'properties': {'attach_emoji': {}}}}}]
        result = await self.plugin.capture_current_tool_evidence('origin', items, definitions, item_schema_version=CONTEXT_ITEM_SCHEMA_VERSION)
        payload = result['modified_kwargs']
        rewritten = payload['items']
        self.assertIn(CASUAL_REACTION_POLICY, rewritten[0]['parts'][-1]['text'])
        self.assertEqual(payload['tool_definitions'], definitions)
        self.assertEqual(len(deserialize_prompt_items(rewritten, item_schema_version=payload['item_schema_version'])), 1)
        self.assertEqual(await self.plugin.capture_current_tool_evidence('origin', rewritten, definitions), {'action': 'continue'})
        self.assertEqual(await self.plugin.capture_current_tool_evidence('origin', items, []), {'action': 'continue'})
        self.plugin.set_plugin_config({'plugin': {'config_version': '1.0.0'}, 'reactions': {'probability': 0}})
        self.assertEqual(await self.plugin.capture_current_tool_evidence('origin', items, definitions), {'action': 'continue'})

    async def test_reaction_probability_dropdown_and_legacy_float(self):
        field = self.plugin.get_webui_config_schema()['sections']['reactions']['fields']['probability']
        self.assertEqual(field['choices'], [0, 0.1, 0.3, 0.5, 0.8, 1])
        self.assertEqual(field['i18n']['zh-CN']['choice:0.8'], '80%')
        for value, expected in (('0.3', 0.3), (0.37, 0.37), ('1', 1)):
            self.plugin.set_plugin_config({'plugin': {'config_version': '1.0.0'}, 'reactions': {'probability': value}})
            self.assertEqual(self.plugin.config.reactions.probability, expected)

    async def test_search_returns_data_to_original_ai_without_direct_qq_send(self):
        settings = ({'desktop_worker': {'enabled': True}}, {}, {})
        with patch('daifeilong.plugin.read_settings', return_value=settings), patch('daifeilong.desktop.run_task', new=AsyncMock(return_value={'id': 'task', 'text': 'answer https://example.com', 'artifacts': []})):
            result = await self.plugin.web_search('latest', stream_id='group-a')
        self.assertIn('https://example.com', result['text'])
        from src.plugin_runtime.component_query import ComponentQueryService
        parsed = ComponentQueryService._parse_tool_invoke_result(SimpleNamespace(name='web_search', plugin_id='local.daifeilong'), result)
        self.assertTrue(parsed.success)
        self.assertIn('answer https://example.com', parsed.content)
        self.plugin.ctx.send.text.assert_not_awaited()

    async def test_codex_analysis_reaches_host_tool_content(self):
        settings = ({'agent_worker': {'enabled': True}}, {}, {})
        with patch('daifeilong.plugin.read_settings', return_value=settings), patch('daifeilong.desktop.run_task', new=AsyncMock(return_value={'id': 'task', 'text': '实际分析结果', 'artifacts': []})):
            result = await self.plugin.ask_codex('question', stream_id='origin')
        from src.plugin_runtime.component_query import ComponentQueryService
        parsed = ComponentQueryService._parse_tool_invoke_result(SimpleNamespace(name='ask_codex', plugin_id='local.daifeilong'), result)
        self.assertEqual(parsed.content, '实际分析结果')

    async def test_images_stay_in_origin_group_and_only_stickers_are_resized(self):
        result = {'id': 'abc123', 'text': 'caption', 'artifacts': [{'id': 'image-id', 'kind': 'image', 'name': 'a.png', 'raw': picture()}]}
        outcome = await self.plugin.deliver_desktop_images(result, 'image', 'group-b')
        self.assertTrue(outcome['sent'])
        args = self.plugin.ctx.send.image.call_args.args
        self.assertEqual(args[1], 'group-b')
        self.assertEqual(Image.open(io.BytesIO(base64.b64decode(args[0]))).size, (480, 360))
        await self.plugin.deliver_desktop_images({**result, 'id': 'sticker'}, 'sticker', 'group-b')
        raw = base64.b64decode(self.plugin.ctx.send.image.call_args.args[0])
        self.assertEqual(Image.open(io.BytesIO(raw)).size, (300, 300))

    async def test_uncertain_qq_send_stops_remaining_deliveries(self):
        self.plugin.ctx.send.image.return_value = {'sent': False}
        result = {'id': 'abc123', 'text': 'caption', 'artifacts': [{'id': 'first', 'kind': 'image', 'name': 'a.png', 'raw': picture()}, {'id': 'second', 'kind': 'image', 'name': 'b.png', 'raw': picture()}]}
        outcome = await self.plugin.deliver_desktop_images(result, 'image', 'group-b')
        self.assertFalse(outcome['success'])
        self.plugin.ctx.send.image.assert_awaited_once()
        self.plugin.ctx.send.text.assert_not_awaited()
        self.plugin.ctx.llm.generate.assert_not_awaited()
        self.assertTrue((self.plugin.ctx.paths.data_dir / 'desktop/abc123/second.png').exists())

    async def test_all_nine_references_keep_edit_original_and_caption_uses_live_profile(self):
        directory = Path(self.cache.name)
        self.plugin.directory = directory
        characters = {}
        for name in ('gpt', 'deepseek', 'gemini', 'grok', 'claude', 'zcode', 'minimax', 'glm', 'qwen'):
            (directory / f'{name}.png').write_bytes(picture())
            characters[name] = {'reference': f'{name}.png', 'appearance': f'{name} 的外观'}
        original = base64.b64encode(picture()).decode()
        self.plugin.ctx.maisaka = SimpleNamespace(context=SimpleNamespace(
            resolve_image=AsyncMock(return_value={'success': True, 'image': {'binary_data_base64': original}}),
        ))
        config = {'images': {'backend': 'codex-acp'}}
        raw_caption = '图片已根据要求完成。'
        output = {'id': 'edit', 'text': raw_caption, 'artifacts': [{'id': 'pic', 'kind': 'image', 'name': 'a.png', 'raw': picture()}]}
        worker = AsyncMock(return_value=output)
        with patch('daifeilong.plugin.read_settings', return_value=(config, {}, characters)), patch('daifeilong.desktop.run_task', new=worker):
            result = await self.plugin.generate_image(
                '把全员加入这张画', characters='all', source_image_id='message', stream_id='origin',
            )
        self.assertTrue(result['sent'])
        _, _, _, prompt, attachments = worker.call_args.args
        self.assertEqual(len(attachments), 4)
        self.assertEqual(attachments[0], ('original.png', picture()))
        for index, name in enumerate(characters, 1):
            self.assertIn(f'{index}. {name}：{name} 的外观', prompt)
        for filename, raw in attachments[1:]:
            self.assertTrue(filename.endswith('.jpg'))
            with Image.open(io.BytesIO(raw)) as sheet:
                self.assertEqual(sheet.size, (1440, 1920))
                for point in ((360, 500), (1080, 500), (360, 1460)):
                    self.assertGreater(sheet.getpixel(point)[2] - sheet.getpixel(point)[0], 200)
        args, kwargs = self.plugin.ctx.llm.generate.call_args
        self.assertEqual(kwargs['task_name'], 'replyer')
        self.assertIn('俏皮地接话\n自然使用喵', args[0][0]['content'])
        self.assertEqual(json.loads(args[0][1]['content']), {'绘图请求': '把全员加入这张画', '作图备注': raw_caption})
        self.plugin.ctx.send.text.assert_awaited_once_with('喵，这幅画拿去挂墙上！', 'origin')

    async def test_library_sticker_probability_and_cooldown_preserve_text_reply(self):
        from src.llm_models.payload_content.context_item import CONTEXT_ITEM_SCHEMA_VERSION, ContextItemMeta, ContextToolCall, FunctionCallItem
        from src.llm_models.payload_content.context_protocol import ContextProtocolMode
        from src.plugin_runtime.hook_payloads import deserialize_prompt_items, serialize_prompt_items

        call = ContextToolCall.create(call_id='reply-1', func_name='reply', args={'msg_id': '42', 'attach_emoji': '忍笑'})
        original = [FunctionCallItem(ContextItemMeta.create(logical_turn_id='turn-1'), call)]
        reply = serialize_prompt_items(original)[0]
        with patch('daifeilong.plugin.random.random', return_value=0.9):
            skipped = await self.plugin.limit_library_sticker('group-a', [reply])
        filtered = deserialize_prompt_items(
            skipped['modified_kwargs']['output_items'], item_schema_version=CONTEXT_ITEM_SCHEMA_VERSION,
            mode=ContextProtocolMode.MODEL_OUTPUT, original_items=original,
        )
        self.assertEqual(filtered[0].tool_call.materialize_args(), {'msg_id': '42'})
        with patch('daifeilong.plugin.random.random', return_value=0.2):
            self.assertEqual(await self.plugin.limit_library_sticker('group-a', [reply]), {'action': 'continue'})
            await self.plugin.remember_sent_sticker({'session_id': 'group-a', 'raw_message': [{'type': 'emoji'}]}, sent=False)
            self.assertEqual(await self.plugin.limit_library_sticker('group-a', [reply]), {'action': 'continue'})
            await self.plugin.remember_sent_sticker({'session_id': 'group-a', 'raw_message': [{'type': 'emoji'}]}, sent=True)
            cooled = await self.plugin.limit_library_sticker('group-a', [reply])
            self.assertEqual(cooled['modified_kwargs']['output_items'][0]['tool_call']['args'], {'msg_id': '42'})
            self.assertEqual(await self.plugin.limit_library_sticker('group-b', [reply]), {'action': 'continue'})

    async def test_library_sticker_rejects_context_only_reference(self):
        reply = {'item_type': 'FunctionCallItem', 'tool_call': {'func_name': 'reply', 'args': {'msg_id': '42', 'attach_emoji': {'msg_id': '43'}}}}
        result = await self.plugin.limit_library_sticker('group-a', [reply])
        self.assertEqual(result['modified_kwargs']['output_items'][0]['tool_call']['args'], {'msg_id': '42'})

    async def test_explicit_desktop_image_ignores_disabled_api_and_casual_probability(self):
        config = {'images': {'backend': 'desktop', 'enabled': False}, 'desktop_worker': {'enabled': True}}
        self.plugin.set_plugin_config({'plugin': {'config_version': '1.0.0'}, 'reactions': {'probability': 0}})
        output = {'id': 'abc123', 'text': '', 'artifacts': [{'id': 'pic', 'kind': 'image', 'name': 'a.png', 'raw': picture()}]}
        with patch('daifeilong.plugin.read_settings', return_value=(config, {}, {})), patch('daifeilong.desktop.run_task', new=AsyncMock(return_value=output)) as worker, patch('daifeilong.plugin.generate') as api:
            result = await self.plugin.generate_image('draw', kind='image', stream_id='origin')
        self.assertTrue(result['sent'])
        worker.assert_awaited_once()
        api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
