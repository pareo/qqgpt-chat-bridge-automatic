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
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugins'))
from daifeilong import desktop
from daifeilong.qq_images import read_group_images
from daifeilong.plugin import (
    ANALYSIS_FACTS_ONLY, CASUAL_REACTION_POLICY, DaifeilongPlugin, PERSONA_VOICE,
    PLANNER_FACTS_ONLY, PLANNER_IMAGE_REQUESTS, REPLYER_WORDING_ONLY,
)


def picture():
    output = io.BytesIO()
    Image.new('RGB', (480, 360), 'blue').save(output, 'PNG')
    return output.getvalue()


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    def test_qq_pre_send_read_or_write_failure_is_retryable_but_timeout_is_not(self):
        from src.platform_io.types import DeliveryStatus
        from src.services.send_service import _qq_media_upload_rejected

        receipt = SimpleNamespace(
            status=DeliveryStatus.FAILED,
            driver_id='gateway:maibot-team.snowluma-adapter:snowluma_gateway',
        )
        batch = SimpleNamespace(route_key=SimpleNamespace(platform='qq'), receipts=[receipt])
        for action in ('send_group_msg', 'send_private_msg'):
            for operation in ('read', 'write'):
                with self.subTest(action=action, operation=operation):
                    receipt.error = f'对端动作返回失败: action={action} message=ENOMEM: not enough memory, {operation}'
                    self.assertTrue(_qq_media_upload_rejected(batch))
        receipt.error = '对端动作返回失败: action=send_group_msg message=request timeout'
        self.assertFalse(_qq_media_upload_rejected(batch))
        receipt.error = '对端动作返回失败: action=send_group_msg message=ENOMEM: not enough memory, write'
        receipt.driver_id = 'other-driver'
        self.assertFalse(_qq_media_upload_rejected(batch))

    async def test_qq_source_rejects_another_group_before_media_fetch(self):
        with patch('daifeilong.qq_images.napcat_message', new=AsyncMock(return_value={
            'group_id': 20, 'message_id': 42, 'message': [{'type': 'image', 'data': {'url': 'https://gchat.qpic.cn/source'}}],
        })), patch('daifeilong.qq_images.download_picture', new=AsyncMock()) as download:
            self.assertEqual(await read_group_images('token', '10', '42'), [])
        download.assert_not_awaited()

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

        async def call_host_method(method, *, payload):
            self.assertEqual(method, 'cap.call')
            self.assertEqual(payload['capability'], 'send.image')
            args = payload['args']
            return await self.plugin.ctx.send.image(
                args['image_base64'], args['stream_id'], return_details=args['return_details'],
            )

        self.plugin._set_context(SimpleNamespace(
            paths=SimpleNamespace(data_dir=Path(self.cache.name)),
            logger=SimpleNamespace(info=lambda *a: None, error=lambda *a: None),
            send=SimpleNamespace(image=AsyncMock(return_value={'sent': True}), text=AsyncMock(return_value=True)),
            call_host_method=call_host_method,
            personality=SimpleNamespace(get_current=AsyncMock(return_value={
                'name': '猫娘模式', 'personality': '俏皮地接话', 'reply_style': '自然使用喵',
            })),
            llm=SimpleNamespace(generate=AsyncMock(return_value={'success': True, 'response': '喵，这幅画拿去挂墙上！'})),
        ))
        await self.plugin.on_load()

    async def test_quote_keeps_original_reply_metadata_and_adds_a_real_image(self):
        from src.plugin_runtime.hook_payloads import deserialize_session_message

        self.plugin.directory = Path(self.cache.name)
        (self.plugin.directory / 'secrets.json').write_text('{"onebot_token":"test"}', encoding='utf-8')
        raw = picture()
        quote = {'type': 'reply', 'data': {'target_message_id': '42', 'target_message_content': '[image]'}}
        message = {'platform': 'qq', 'message_id': '43', 'timestamp': '1795157476',
                   'message_info': {'group_info': {'group_id': '10', 'group_name': 'test'},
                                    'user_info': {'user_id': '23', 'user_nickname': 'tester'}},
                   'raw_message': [quote, {'type': 'text', 'data': '这是什么？'}]}
        with patch('daifeilong.plugin.read_group_images', new=AsyncMock(return_value=[('test.png', raw)])) as read:
            updated = (await self.plugin.include_qq_quote_images(message))['modified_kwargs']['message']
        read.assert_awaited_once_with('test', '10', '42')
        self.assertEqual(updated['raw_message'][0], quote)
        restored = deserialize_session_message(updated)
        self.assertTrue(restored.is_picture)
        self.assertEqual(restored.raw_message.components[-1].binary_data, raw)

    async def test_edit_uses_only_the_current_qq_group_on_cache_miss(self):
        self.plugin.ctx.maisaka = SimpleNamespace(context=SimpleNamespace(
            resolve_image=AsyncMock(return_value={'success': False})))
        self.plugin.ctx.chat = SimpleNamespace(get_all_streams=AsyncMock(return_value=[
            {'session_id': 'other', 'platform': 'qq', 'group_id': '11', 'is_group_session': True},
            {'session_id': 'here', 'platform': 'qq', 'group_id': '12', 'is_group_session': True},
        ]))
        originals = [('original-1.png', picture())]
        with patch('daifeilong.plugin.read_group_images', new=AsyncMock(return_value=originals)) as read:
            self.assertEqual(await self.plugin.resolve_edit_images('here', '42', {'onebot_token': 'token'}), originals)
        read.assert_awaited_once_with('token', '12', '42')

    async def test_animation_sends_and_caches_a_multiframe_gif(self):
        sheet = Image.new('RGB', (600, 600), 'white')
        draw = ImageDraw.Draw(sheet)
        for index in range(9):
            x, y = (index % 3) * 200, (index // 3) * 200
            draw.ellipse((x + 30 + index * 5, y + 40, x + 85 + index * 5, y + 95), fill='blue')
        buffer = io.BytesIO()
        sheet.save(buffer, 'PNG')
        outcome = await self.plugin.deliver_desktop_images({
            'id': 'test-animation',
            'artifacts': [{'kind': 'image', 'id': 'sheet', 'raw': buffer.getvalue()}],
        }, 'animation', 'here', prompt='蓝色球')
        self.assertTrue(outcome['sent'])
        payload = base64.b64decode(self.plugin.ctx.send.image.await_args.args[0])
        with Image.open(io.BytesIO(payload)) as image:
            self.assertEqual((image.format, image.n_frames, image.info['loop']), ('GIF', 9, 0))
        self.assertEqual((Path(self.cache.name) / 'desktop/test-animation/sheet.gif').read_bytes(), payload)

    async def test_ordinary_reply_preserves_existing_prompt_and_applies_persona_voice(self):
        for message_id in ('123', ''):
            with self.subTest(message_id=message_id):
                result = await self.plugin.supply_current_tool_evidence(
                    session_id='origin', reply_message_id=message_id, extra_prompt='回答简短一些',
                    reply_tool_args={
                        'msg_id': message_id, 'reply_reference': '群友要求用两句说明',
                        'attach_pic': [{'msg_id': 'image-1', 'index': 0}],
                        'reply_style': '长回复', 'expression_intent': {'tone': '客服腔'},
                    },
                    model_name='reply-model',
                )
                self.assertEqual(result['modified_kwargs']['extra_prompt'], '\n\n'.join(('回答简短一些', PERSONA_VOICE, REPLYER_WORDING_ONLY)))
                self.assertEqual(result['modified_kwargs']['reply_tool_args'], {
                    'msg_id': message_id, 'reply_reference': '群友要求用两句说明',
                    'attach_pic': [{'msg_id': 'image-1', 'index': 0}],
                })
                self.assertEqual(result['modified_kwargs']['model_name'], 'reply-model')
        self.plugin.ctx.llm.generate.assert_not_awaited()

    async def test_planner_keeps_required_facts_and_attachment_actions(self):
        properties = {name: {} for name in (
            'msg_id', 'reply_reference', 'reply_style', 'expression_intent', 'after_reply', 'attach_pic', 'attach_at',
        )}
        reply = {'type': 'function', 'function': {'name': 'reply', 'parameters': {
            'properties': properties, 'required': ['msg_id', 'reply_reference'],
        }}}
        search = {'type': 'function', 'function': {'name': 'web_search', 'parameters': {}}}
        items = [{'item_type': 'SystemMessageItem', 'parts': [{'type': 'text', 'text': '原提示'}]}]
        result = await self.plugin.capture_current_tool_evidence('origin', items, [reply, search])
        updated, same_search = result['modified_kwargs']['tool_definitions']
        parameters = updated['function']['parameters']
        self.assertEqual(parameters['required'], ['msg_id', 'reply_reference'])
        self.assertEqual(set(parameters['properties']), {
            'msg_id', 'reply_reference', 'after_reply', 'attach_pic', 'attach_at',
        })
        self.assertIn('群友明确要求的格式或长度', parameters['properties']['reply_reference']['description'])
        self.assertEqual(same_search, search)
        self.assertIn('reply_style', properties)

        facts = {'msg_id': '42', 'reply_reference': '群友要求分两点', 'attach_at': ['43'], 'after_reply': 'stop'}
        call = {'item_type': 'FunctionCallItem', 'tool_call': {'func_name': 'reply', 'args': {
            **facts, 'reply_style': '简短表达', 'expression_intent': {'tone': '委婉'},
        }}}
        outcome = await self.plugin.limit_library_sticker('origin', [call])
        self.assertEqual(outcome['modified_kwargs']['output_items'][0]['tool_call']['args'], facts)
        self.assertEqual(await self.plugin.skip_upstream_wording_selection(candidates=[{'id': 1}]),
                         {'action': 'continue', 'modified_kwargs': {'candidates': []}})

        self.plugin.set_plugin_config({'plugin': {'config_version': '1.0.0'}, 'reply_voice': {'replyer_only': False}})
        self.assertEqual(await self.plugin.capture_current_tool_evidence('origin', items, [reply, search]),
                         {'action': 'continue'})
        self.assertEqual(await self.plugin.limit_library_sticker('origin', [call]), {'action': 'continue'})
        self.assertEqual(await self.plugin.skip_upstream_wording_selection(), {'action': 'continue'})

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
        no_sticker = await self.plugin.capture_current_tool_evidence('origin', items, definitions)
        self.assertIn(PLANNER_FACTS_ONLY, no_sticker['modified_kwargs']['items'][0]['parts'][-1]['text'])
        self.assertNotIn(CASUAL_REACTION_POLICY, str(no_sticker['modified_kwargs']['items']))

    async def test_image_request_hint_applies_before_deferred_tool_is_discovered(self):
        items = [{'item_type': 'SystemMessageItem', 'parts': [{'type': 'text', 'text': '原提示'}]}]
        discovery = {'type': 'function', 'function': {'name': 'tool_search'}}
        image = {'type': 'function', 'function': {'name': 'generate_image'}}
        for definition in (discovery, image):
            result = await self.plugin.capture_current_tool_evidence('origin', items, [definition])
            plan = result['modified_kwargs']['items'][0]['parts'][-1]['text']
            self.assertIn(PLANNER_IMAGE_REQUESTS, plan)
            self.assertIn('query 填 generate_image', plan)
            self.assertIn('“看看你的 OOTD”', plan)
        self.assertEqual(await self.plugin.capture_current_tool_evidence('origin', items, []),
                         {'action': 'continue'})

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
        self.assertNotIn('用当前人设', parsed.content)
        self.plugin.ctx.send.text.assert_not_awaited()

    async def test_codex_analysis_reaches_host_tool_content(self):
        settings = ({'agent_worker': {'enabled': True}}, {}, {})
        with patch('daifeilong.plugin.read_settings', return_value=settings), patch('daifeilong.desktop.run_task', new=AsyncMock(return_value={'id': 'task', 'text': '实际分析结果', 'artifacts': []})) as worker:
            result = await self.plugin.ask_codex('question', stream_id='origin')
        self.assertEqual(worker.await_args.args[3], ANALYSIS_FACTS_ONLY + 'question')
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

    async def test_qq_media_rejection_retries_once_after_delay_with_smaller_image(self):
        buffer = io.BytesIO()
        Image.new('RGB', (480, 360), 'navy').save(buffer, 'PNG', compress_level=0)
        original = buffer.getvalue()
        # The Host's raw result contains a success key, which makes the SDK
        # helper strip the very failure code the plugin needs.
        from maibot_sdk.context import PluginContext
        rejection = {'success': False, 'sent': False, 'message_id': None, 'error_code': 'qq_media_transfer_failed'}
        normalized = PluginContext._normalize_capability_result('send.image', rejection, return_details=True)
        self.assertNotIn('error_code', normalized)
        result = {'id': 'retry-task', 'text': '', 'artifacts': [
            {'id': 'image-id', 'kind': 'image', 'name': 'picture.png', 'raw': original},
        ]}
        with patch('daifeilong.plugin.asyncio.sleep', new_callable=AsyncMock) as pause:
            async def send(encoded, stream_id, *, return_details):
                self.assertEqual(stream_id, 'group-b')
                self.assertTrue(return_details)
                raw = base64.b64decode(encoded)
                if self.plugin.ctx.send.image.await_count == 1:
                    pause.assert_not_awaited()
                    self.assertEqual(raw, original)
                else:
                    pause.assert_awaited_once_with(4)
                    self.assertLess(len(raw), len(original))
                    with Image.open(io.BytesIO(raw)) as image:
                        self.assertEqual(image.size, (480, 360))
                        self.assertEqual(image.format, 'JPEG')
                return rejection

            self.plugin.ctx.send.image.side_effect = send
            outcome = await self.plugin.deliver_desktop_images(result, 'image', 'group-b')
        self.assertFalse(outcome['success'])
        self.assertEqual(self.plugin.ctx.send.image.await_count, 2)
        self.assertEqual((self.plugin.ctx.paths.data_dir / 'desktop/retry-task/image-id.png').read_bytes(), original)
        self.plugin.ctx.llm.generate.assert_not_awaited()

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
