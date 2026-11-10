"""Dependency-free checks for reply-policy migration and internal evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins'))
from daifeilong.search_result import (
    apply_reply_policy, search_content, SEARCH_REPLY_RULE,
    LEGACY_SEARCH_REPLY_RULE, LEGACY_SEARCH_HANDOFF, LEGACY_SUMMARY_RULE, evidence_body,
)


class SearchPolicyTests(unittest.TestCase):
    def test_migrates_old_url_requirement_once_without_changing_persona(self):
        custom = '自定义人设。保留我提供的链接 https://example.com/my-profile'
        original = custom + '\n' + LEGACY_SEARCH_HANDOFF + '\n' + LEGACY_SEARCH_REPLY_RULE
        bot = {'chat': {'reply_style': {'group_chat_prompt': original}}}
        self.assertEqual(apply_reply_policy(bot), 2)
        migrated = bot['chat']['reply_style']['group_chat_prompt']
        self.assertTrue(migrated.startswith(custom))
        self.assertNotIn(LEGACY_SEARCH_REPLY_RULE, migrated)
        self.assertNotIn(LEGACY_SEARCH_HANDOFF, migrated)
        self.assertEqual(migrated.count(SEARCH_REPLY_RULE), 1)
        self.assertEqual(apply_reply_policy(bot), 0)

    def test_evidence_keeps_urls_but_requests_persona_summary(self):
        raw = '来源正文 https://example.com/article'
        content = search_content(raw)
        self.assertIn(raw, content)
        self.assertIn('用当前人设', content)
        self.assertIn('不要只回复网页', content)
        self.assertIn('用户明确索要原文、链接', content)
        self.assertIn('不把传闻说成事实', content)

    def test_previous_summary_policy_is_replaced_without_touching_persona(self):
        bot = {'chat': {'reply_style': {'private_chat_prompts': '自定义人设\n' + LEGACY_SUMMARY_RULE}}}
        apply_reply_policy(bot)
        prompt = bot['chat']['reply_style']['private_chat_prompts']
        self.assertTrue(prompt.startswith('自定义人设\n'))
        self.assertNotIn(LEGACY_SUMMARY_RULE, prompt)
        self.assertEqual(prompt.count(SEARCH_REPLY_RULE), 1)
        self.assertEqual(apply_reply_policy(bot), 0)

    def test_unwrap_does_not_remove_source_text_that_only_looks_like_instructions(self):
        raw = '网页原文\n\n回复处理要求：这仍然是网页内容'
        self.assertEqual(evidence_body(raw), raw)
        self.assertEqual(evidence_body(search_content(raw)), raw)


if __name__ == '__main__':
    unittest.main()
