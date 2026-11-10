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
from daifeilong.plugin import DaifeilongPlugin


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
        ))
        await self.plugin.on_load()

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
        self.assertTrue((self.plugin.ctx.paths.data_dir / 'desktop/abc123/second.png').exists())

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
