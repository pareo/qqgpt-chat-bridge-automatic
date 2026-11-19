from datetime import datetime
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins'))
from daifeilong.plugin import DaifeilongPlugin
from daifeilong.word_filter import BLOCKED_NOTICE, UNAVAILABLE_NOTICE, WordFilter


class WordFilterTests(unittest.TestCase):
    def test_normalizes_and_reloads_words_without_restarting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'blocked_words.txt'
            path.write_text('# ignore this\n\n测试词\nＡＢＣ\n', encoding='utf-8-sig')
            word_filter = WordFilter(path)
            self.assertIsNone(word_filter.notice('打舞萌去 # ignore this'))
            self.assertEqual(word_filter.notice('测\u200b试词'), BLOCKED_NOTICE)
            self.assertEqual(word_filter.notice('abc'), BLOCKED_NOTICE)

            updated = path.with_suffix('.new')
            updated.write_text('另一个词\n', encoding='utf-8')
            updated.replace(path)
            self.assertIsNone(word_filter.notice('测试词'))
            self.assertEqual(word_filter.notice('另一个词'), BLOCKED_NOTICE)

    def test_keeps_last_good_list_if_edit_is_unreadable_or_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'blocked_words.txt'
            word_filter = WordFilter(path)
            self.assertEqual(word_filter.notice('一段话'), UNAVAILABLE_NOTICE)
            path.write_text('测试词\n', encoding='utf-8')
            self.assertEqual(word_filter.notice('测试词'), BLOCKED_NOTICE)
            path.write_bytes(b'\xff')
            self.assertEqual(word_filter.notice('测试词'), BLOCKED_NOTICE)
            path.write_text('# only a comment', encoding='utf-8')
            self.assertEqual(word_filter.notice('测试词'), BLOCKED_NOTICE)
            self.assertIsNone(word_filter.notice('正常内容'))


class WordFilterHookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.words = Path(cache.name) / 'blocked_words.txt'
        self.words.write_text('测试词\n发言过滤\n', encoding='utf-8')
        self.streams = AsyncMock(return_value=[
            {'session_id': 'test-qq', 'platform': 'qq'},
            {'session_id': 'owner-webui', 'platform': 'internal'},
            {'session_id': 'test-telegram', 'platform': 'telegram'},
        ])
        self.send = AsyncMock()
        self.logger = Mock()
        self.plugin = DaifeilongPlugin()
        self.plugin._set_context(SimpleNamespace(chat=SimpleNamespace(get_all_streams=self.streams),
                                                 send=self.send, logger=self.logger))
        self.plugin.set_plugin_config({'plugin': {'config_version': '1.0.0'}, 'moderation': {'enabled': True}})
        with patch.dict('os.environ', {'DAIFEILONG_CONFIG_DIR': cache.name}):
            await self.plugin.on_load()

    async def test_disabled_filter_passes_both_paths(self):
        self.plugin.set_plugin_config({})
        self.assertEqual(await self.plugin.filter_qq_reply('测试词', 'test-qq'), {'action': 'continue'})
        self.assertEqual(await self.plugin.filter_outgoing_qq_text({'platform': 'qq', 'raw_message': [
            {'type': 'text', 'data': '测试词'},
        ]}), {'action': 'continue'})
        self.streams.assert_not_awaited()

    async def test_reply_is_replaced_before_splitting_and_notice_passes_final_hook(self):
        from src.maisaka.builtin_tool.reply import _invoke_before_post_process_hook
        from src.plugin_runtime.host.hook_dispatcher import HookDispatchResult

        async def invoke_hook(name, **kwargs):
            self.assertEqual(name, 'maisaka.reply.before_post_process')
            action = await self.plugin.filter_qq_reply(**kwargs)
            return HookDispatchResult(name, {**kwargs, **action.get('modified_kwargs', {})})

        context = SimpleNamespace(runtime=SimpleNamespace(session_id='test-qq'),
                                  get_runtime_manager=lambda: SimpleNamespace(invoke_hook=invoke_hook))
        response, options = await _invoke_before_post_process_hook(context, '第一句话。这里有测试词。', 'question', {})
        self.assertEqual(response, BLOCKED_NOTICE)
        self.assertTrue(options['skip_post_process'])
        self.assertEqual(await self.plugin.filter_outgoing_qq_text({'platform': 'qq', 'raw_message': [
            {'type': 'text', 'data': response},
        ]}), {'action': 'continue'})
        self.logger.warning.assert_called_once()
        self.assertNotIn('测试词', self.logger.warning.call_args.args[0])
        self.send.assert_not_called()

    async def test_direct_send_replaces_text_and_preserves_qq_route(self):
        from src.chat.message_receive.message import SessionMessage
        from src.common.data_models.mai_message_data_model import GroupInfo, MessageInfo, UserInfo
        from src.common.data_models.message_component_data_model import MessageSequence, TextComponent
        from src.plugin_runtime.host.hook_dispatcher import HookDispatchResult
        from src.services.send_service import _invoke_send_hook

        async def invoke_hook(name, **kwargs):
            self.assertEqual(name, 'send_service.before_send')
            action = await self.plugin.filter_outgoing_qq_text(**kwargs)
            return HookDispatchResult(name, {**kwargs, **action.get('modified_kwargs', {})})

        message = SessionMessage('outgoing', datetime.now(), 'qq')
        message.account_id = '100001'
        message.scope = 'group'
        message.session_id = 'test-qq'
        message.message_info = MessageInfo(UserInfo('100001', 'Bot'), GroupInfo('200001', '测试'))
        message.raw_message = MessageSequence(components=[TextComponent(text='测试'), TextComponent(text='词')])
        message.processed_plain_text = '测试词'
        with patch('src.services.send_service._get_runtime_manager', return_value=SimpleNamespace(invoke_hook=invoke_hook)):
            result, replacement = await _invoke_send_hook('send_service.before_send', message, typing=True, set_reply=True)
        self.assertEqual([part.text for part in replacement.raw_message.components], [BLOCKED_NOTICE])
        self.assertEqual(replacement.processed_plain_text, BLOCKED_NOTICE)
        self.assertEqual(replacement.message_info.group_info.group_id, '200001')
        self.assertEqual(replacement.account_id, '100001')
        self.assertFalse(result.kwargs['set_reply'])
        self.assertFalse(result.kwargs['typing'])
        self.send.assert_not_called()

    async def test_owner_webui_reply_shows_notice_when_word_or_lookup_fails(self):
        response = await self.plugin.filter_qq_reply('测试词', 'owner-webui')
        self.assertEqual(response['modified_kwargs'], {'response': BLOCKED_NOTICE, 'skip_post_process': True})
        direct = await self.plugin.filter_outgoing_qq_text({
            'platform': 'internal', 'raw_message': [{'type': 'text', 'data': '测试词'}],
        })
        self.assertEqual(direct['modified_kwargs']['message']['processed_plain_text'], BLOCKED_NOTICE)
        self.streams.return_value = {'success': False, 'error': 'lookup failed'}
        response = await self.plugin.filter_qq_reply('测试词', 'owner-webui')
        self.assertEqual(response['modified_kwargs'], {'response': UNAVAILABLE_NOTICE, 'skip_post_process': True})

    async def test_clean_text_other_platform_and_images_pass_through(self):
        self.assertEqual(await self.plugin.filter_qq_reply('正常聊舞萌', 'test-qq'), {'action': 'continue'})
        self.streams.assert_not_awaited()
        self.assertEqual(await self.plugin.filter_qq_reply('测试词', 'test-telegram'), {'action': 'continue'})
        self.streams.assert_awaited_once_with(platform='all_platforms')
        for platform, segment in (('qq', {'type': 'image', 'data': '测试词'}),
                                  ('telegram', {'type': 'text', 'data': '测试词'})):
            self.assertEqual(await self.plugin.filter_outgoing_qq_text({'platform': platform, 'raw_message': [segment]}),
                             {'action': 'continue'})
        self.logger.warning.assert_not_called()
