import re
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins'))
from daifeilong import maimai
from daifeilong.plugin import DaifeilongPlugin


class MaimaiTests(unittest.IsolatedAsyncioTestCase):
    async def test_alias_lookup_keeps_standard_and_dx_separate_and_caches_catalog(self):
        routes = []

        def respond(request):
            routes.append(request.url.path)
            self.assertNotIn('Authorization', request.headers)
            if request.url.host == 'www.yuzuchan.moe':
                return httpx.Response(200, json={'content': [{'SongID': 42, 'Alias': ['水神2']}]})
            return httpx.Response(200, json=[
                {'id': '42', 'title': 'Test Song', 'type': 'SD', 'level': ['3', '6', '10', '14'], 'ds': [3, 6, 10, 14.1]},
                {'id': '10042', 'title': 'Test Song', 'type': 'DX', 'level': ['4', '7', '11', '14+'], 'ds': [4, 7, 11, 14.7]},
                {'id': '43', 'title': 'Test Song 2', 'type': 'SD', 'level': ['3', '6', '10', '14'], 'ds': [3, 6, 10, 14.1]},
            ])

        async with httpx.AsyncClient(base_url=maimai.BASE, transport=httpx.MockTransport(respond)) as client:
            catalog = maimai.SongCatalog()
            both = await catalog.describe(client, '水神2　紫')
            one = await catalog.describe(client, '10042 14+')
            self.assertEqual(both, await catalog.describe(client, '水神2｜紫'))
            self.assertIn('DX 绿4（定数 4）', await catalog.describe(client, '10042'))
            self.assertIn('Test Song 2 · ID 43', await catalog.describe(client, 'Test Song 2'))
            self.assertIn('DX 紫14+（定数 14.7）', await catalog.describe(client, 'Test Song MASTER'))
        self.assertIn('标准 紫14（定数 14.1）', both)
        self.assertIn('DX 紫14+（定数 14.7）', both)
        self.assertNotIn('绿', both)
        self.assertIn('DX 紫14+（定数 14.7）', one)
        self.assertNotIn('标准', one)
        self.assertEqual(len(routes), 2)

    async def test_b50_command_checks_sender_then_sends_image_to_origin(self):
        requests = []
        score = {'title': '<img>', 'achievements': 100.5, 'ra': 310, 'level': '14+', 'level_index': 3, 'type': 'DX'}

        def respond(request):
            requests.append(request.url.path)
            if request.url.path == '/.well-known/openid-configuration':
                return httpx.Response(200, json={'token_endpoint': maimai.AUTH + '/oauth/token'})
            if request.url.path == '/oauth/token':
                params = parse_qs(request.content.decode())
                self.assertEqual(params['subject'], ['ref:' + maimai.subject_ref('12345', 'app', 'secret')])
                self.assertEqual(params['scope'], [maimai.READ])
                return httpx.Response(200, json={'access_token': 'test-access-token'})
            self.assertEqual(request.headers['Authorization'], 'Bearer test-access-token')
            self.assertEqual(request.content, b'{"b50":true}')
            return httpx.Response(200, json={'rating': 310, 'nickname': '<script>', 'charts': {'dx': [score], 'sd': []}})

        plugin = DaifeilongPlugin()
        render = AsyncMock(return_value={'image_base64': 'rendered-png'})
        send = SimpleNamespace(text=AsyncMock(return_value=True), image=AsyncMock(return_value={'sent': True}))
        plugin._set_context(SimpleNamespace(render=SimpleNamespace(html2png=render), send=send,
                                            logger=SimpleNamespace(info=lambda *_: None, error=lambda *_: None)))
        await plugin.on_load()
        command = next(component for component in plugin.get_components() if component['name'] == 'daifeilong_maimai')
        pattern = re.compile(command['metadata']['command_pattern'])
        self.assertIsNotNone(pattern.search('/b50'))
        self.assertIsNotNone(pattern.search('/绑定'))
        self.assertIsNotNone(pattern.search('/更新'))
        self.assertIsNotNone(pattern.search('/查分帮助'))
        self.assertEqual(pattern.search('/HELP').group('action').lower(), 'help')
        self.assertEqual(pattern.search('/查歌 10042').group('query'), '10042')
        self.assertEqual(pattern.search('/查歌 水神2 紫').group('query'), '水神2 紫')
        self.assertIsNone(pattern.search('/舞萌 B50'))
        self.assertIsNone(pattern.search('/B50 other-player'))
        matched_groups = pattern.search('/B50').groupdict()
        client = httpx.AsyncClient(base_url=maimai.BASE, transport=httpx.MockTransport(respond))
        with patch('daifeilong.plugin.httpx.AsyncClient', return_value=client), patch('daifeilong.maimai.load_settings', return_value=(None, 'app', 'secret')):
            result = await plugin.maimai_command(
                stream_id='origin', platform='qq', user_id='12345', matched_groups=matched_groups,
            )
        self.assertTrue(result)
        self.assertEqual(requests, ['/.well-known/openid-configuration', '/oauth/token', '/api/maimaidxprober/query/player'])
        markup = render.await_args.args[0]
        self.assertIn('100.5000%', markup)
        self.assertIn('&lt;script&gt;', markup)
        self.assertIn('&lt;img&gt;', markup)
        self.assertFalse(render.await_args.kwargs['allow_network'])
        send.image.assert_awaited_once_with('rendered-png', 'origin', return_details=True)
        send.text.assert_not_awaited()
        with patch('daifeilong.plugin.httpx.AsyncClient') as unexpected_client:
            await plugin.maimai_command(stream_id='origin', platform='qq', matched_groups=pattern.search('/help').groupdict())
        unexpected_client.assert_not_called()
        help_text, help_origin = send.text.await_args.args
        self.assertEqual(help_origin, 'origin')
        for usage in ('/绑定', '/B50', '/查歌 <曲名、别名或数字 ID> [难度]', '水神2 紫', '10042', '/更新', '/模式', '/help',
                      '附图提问', '文本文件', '联网查', '深入分析', '生图', '改图', '表情包', '表格转图片'):
            self.assertIn(usage, help_text)
        self.assertEqual(help_text.count('/查歌'), 1)
        self.assertEqual(help_text.count('/模式'), 1)

    async def test_update_posts_html_once_and_reports_unknown_if_request_is_lost(self):
        paths = []

        def respond(request):
            self.assertEqual(request.method, 'POST')
            self.assertEqual(request.content, b'<html></html>')
            self.assertEqual(request.headers['Content-Type'], 'text/plain; charset=utf-8')
            paths.append(request.url.path)
            raise httpx.ReadTimeout('lost response', request=request)

        async with httpx.AsyncClient(base_url=maimai.BASE, transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(maimai.MaimaiError, '导入结果未确认'):
                await maimai.request(client, 'POST', maimai.BASE + '/player/update_records_html', importing=True,
                                     headers={'Content-Type': 'text/plain; charset=utf-8'}, content=b'<html></html>')
        self.assertEqual(paths, ['/api/maimaidxprober/player/update_records_html'])
