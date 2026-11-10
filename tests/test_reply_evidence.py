import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins'))
from daifeilong.reply_evidence import ReplyEvidence

def message(identifier):
    return {'item_type': 'UserMessageItem', 'parts': [{'type': 'text', 'text': f'<message msg_id="{identifier}" time="20:00" user="tester">\nquestion'}]}

def result(text='Found evidence https://example.com/source; not independently verified'):
    return {'item_type': 'FunctionCallOutputItem', 'tool_name': 'web_search', 'output': text}

class EvidenceTests(unittest.TestCase):
    def test_actual_host_serialization_can_be_captured(self):
        from src.llm_models.payload_content.context_item import ContextItemMeta, FunctionCallOutputItem
        from src.plugin_runtime.hook_payloads import serialize_prompt_items
        item = FunctionCallOutputItem(meta=ContextItemMeta.create(logical_turn_id='verification'), call_id='test-call', output='Evidence https://example.com', tool_name='web_search', success=True)
        serialized = serialize_prompt_items([item])
        cache = ReplyEvidence()
        cache.capture('a', [message('123'), *serialized])
        self.assertIn('Evidence https://example.com', cache.prompt('a', '123'))

    def test_full_body_and_link_survive_replyer_chat_history_filter(self):
        cache = ReplyEvidence()
        cache.capture('session-a', [message('123'), result()])
        prompt = cache.prompt('session-a', '123', 'existing instructions')
        self.assertIn('https://example.com/source', prompt)
        self.assertIn('not independently verified', prompt)
        self.assertTrue(prompt.startswith('existing instructions'))
        self.assertIn('用当前人设', prompt)
        self.assertIn('不要只回复网页', prompt)
        self.assertIn('URL供内部核验', prompt)
        self.assertIsNone(cache.prompt('session-b', '123'))
        self.assertIsNone(cache.prompt('session-a', '124'))

    def test_new_message_does_not_reuse_previous_search(self):
        cache = ReplyEvidence()
        cache.capture('a', [message('old'), result(), message('new')])
        self.assertIsNone(cache.prompt('a', 'new'))
        self.assertIsNone(cache.prompt('a', 'old'))

    def test_tool_wrapper_is_not_repeated_in_replyer_but_facts_survive(self):
        from daifeilong.search_result import search_content, SEARCH_REPLY_RULE
        raw = '发布了新功能，镜像记录未直接核实 https://example.com/source'
        cache = ReplyEvidence()
        cache.capture('a', [message('123'), result(search_content(raw))])
        prompt = cache.prompt('a', '123')
        self.assertIn(raw, prompt)
        self.assertNotIn(SEARCH_REPLY_RULE, prompt)
        self.assertNotIn('回复处理要求：', prompt)
        self.assertIn('固定免责声明', prompt)

    def test_old_assistant_text_and_other_tools_are_not_evidence(self):
        cache = ReplyEvidence()
        cache.capture('a', [message('123'), {'item_type': 'AssistantMessageItem', 'output': 'fake'}, {'item_type': 'FunctionCallOutputItem', 'tool_name': 'reply', 'output': 'fake'}])
        self.assertIsNone(cache.prompt('a', '123'))

    def test_expiration(self):
        cache = ReplyEvidence()
        with patch('daifeilong.reply_evidence.time.monotonic', return_value=1):
            cache.capture('a', [message('123'), result()])
        with patch('daifeilong.reply_evidence.time.monotonic', return_value=182):
            self.assertIsNone(cache.prompt('a', '123'))
