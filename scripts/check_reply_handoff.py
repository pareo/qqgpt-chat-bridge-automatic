"""Replay actual recorded Replyer context through the evidence hooks; no IM sends."""
import asyncio
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, '/project/plugins')
sys.path.insert(0, '/MaiMBot')
os.environ['MAIBOT_SHARED_MODEL_CATALOG'] = '/MaiMBot/host/model_catalog.toml'
from daifeilong.plugin import DaifeilongPlugin
from daifeilong.search_result import evidence_body, LEGACY_SUMMARY_RULE, SEARCH_REPLY_RULE
from src.plugin_runtime.hook_payloads import deserialize_prompt_items
from src.llm_models.payload_content.context_item import CONTEXT_ITEM_SCHEMA_VERSION, ContextItemBuilder
from src.llm_models.utils_model import LLMOrchestrator

async def main():
    connection = sqlite3.connect('file:/MaiMBot/data/MaiBot.db?mode=ro', uri=True)
    records = [json.loads(row[0]) for row in connection.execute("select tool_data from tool_records where json_extract(tool_data, '$.call_id') in (?, ?)", (sys.argv[1], sys.argv[2]))]
    search = next(r for r in records if r.get('call_id') == sys.argv[1])
    reply = next(r for r in records if r.get('call_id') == sys.argv[2])
    session = reply['session_id']
    assert search['session_id'] == session
    items = reply['metadata']['monitor_detail']['request_messages']
    omitted_images = 0
    for item in items:
        for index, part in enumerate(item.get('parts', [])):
            if part.get('type') == 'image' and not (isinstance(part.get('image_format'), str) and isinstance(part.get('image_base64'), str)):
                item['parts'][index] = {'type': 'text', 'text': '[历史图片已在日志中脱敏，此次仅重放文字搜索问题，不推测图片内容。]'}
                omitted_images += 1
    text = search['history_content']
    # These are the same Host Context Item shapes observed before its Replyer
    # history filter; the original final Replyer request has no tool output.
    planner_items = items + [{'item_type': 'FunctionCallOutputItem', 'tool_name': 'web_search', 'output': text, 'success': True}]
    plugin = DaifeilongPlugin()
    plugin.set_plugin_config({})
    plugin._set_context(SimpleNamespace(logger=SimpleNamespace(info=lambda *a: None)))
    await plugin.on_load()
    await plugin.capture_current_tool_evidence(session_id=session, items=planner_items)
    injected = await plugin.supply_current_tool_evidence(session_id=session, reply_message_id=reply['arguments']['msg_id'])
    evidence = injected.get('modified_kwargs', {}).get('extra_prompt', '')
    assert evidence_body(text) in evidence, 'Evidence did not reach Replyer hook'
    replaced = False
    for item in items:
        for part in item.get('parts', []):
            if part.get('type') != 'text':
                continue
            if item.get('item_type') == 'SystemMessageItem':
                part['text'] = part['text'].replace(LEGACY_SUMMARY_RULE, SEARCH_REPLY_RULE)
            if 'current_message_tool_evidence' in part['text']:
                part['text'] = part['text'].split('\n\n【额外回复要求】', 1)[0] + '\n\n【额外回复要求】\n' + evidence
                replaced = True
    restored = deserialize_prompt_items(items, item_schema_version=CONTEXT_ITEM_SCHEMA_VERSION)
    if not replaced:
        restored.append(ContextItemBuilder().add_text_part(evidence).build())
    output = await LLMOrchestrator('replyer', request_type='deployment.recorded_reply_handoff').generate_response_with_context_async(lambda client: restored, max_tokens=1800)
    urls = [url for url in re.findall(r'https?://[^\s<>\[\]，。]+', text) if url.rstrip('/)') != 'https://example.com/profile']
    source_present = any(url.rstrip(')') in output.response for url in urls)
    summary_ok = any(word in output.response for word in ('Pro', '额度', '安全', '图像', '重置', 'dot', '电脑', '机器'))
    narrative = re.sub(r'https?://\S+', '', output.response).strip()
    summary_ok = summary_ok and len(narrative) >= 30
    record = {'reply': output.response, 'actual_recorded_history_replayed': True, 'redacted_history_images_omitted': omitted_images, 'evidence_hook_used': True, 'evidence_chars': len(text), 'source_url_present': source_present, 'summary_preserved': summary_ok, 'qq_messages_sent': 0}
    Path('/MaiMBot/data/verification/recorded-reply-handoff.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(json.dumps(record, ensure_ascii=False))
    if not summary_ok:
        raise RuntimeError('Recorded Replyer replay still lost evidence')

asyncio.run(main())
