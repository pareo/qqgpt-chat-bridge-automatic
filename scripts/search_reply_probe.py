"""Check cached evidence summarization with the active reply model; no QQ sends."""
import asyncio
import json
import os
import re
from pathlib import Path
import sys
import httpx
import tomlkit
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, '/project/plugins')
sys.path.insert(0, '/MaiMBot')
os.environ['MAIBOT_SHARED_MODEL_CATALOG'] = '/MaiMBot/host/model_catalog.toml'
from daifeilong.plugin import DaifeilongPlugin
from src.plugin_runtime.component_query import ComponentQueryService
from src.llm_models.utils_model import LLMOrchestrator

async def main():
    credentials = json.loads(Path('/project/config/local/secrets.json').read_text(encoding='utf-8-sig'))
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        response = await client.get('http://codex-worker:18121/v1/tasks/' + sys.argv[1], headers={'Authorization': 'Bearer ' + credentials['agent_worker_token']})
        response.raise_for_status()
        job = response.json()
    assert job['state'] == 'succeeded'
    live = tomlkit.parse(Path('/MaiMBot/config/bot_config.toml').read_text())
    profile = next((p for p in live['personality'].get('profiles', []) if p['name'] == live['personality'].get('selected_profile')), {})
    persona = profile.get('personality', live['personality'].get('personality', ''))
    scope = sys.argv[2] if len(sys.argv) > 2 else 'private'
    want_links = len(sys.argv) > 3 and sys.argv[3] == 'links'
    key = 'private_chat_prompts' if scope == 'private' else 'group_chat_prompt'
    reply_rules = profile.get(key, live['chat']['reply_style'].get(key, ''))
    plugin = DaifeilongPlugin()
    plugin.set_plugin_config({})
    plugin.directory = Path('/project/config/local')
    with patch('daifeilong.desktop.run_task', new=AsyncMock(return_value={'id': job['id'], 'text': job['result']['text'], 'artifacts': []})):
        returned = await plugin.web_search(job['kind'], stream_id='internal-verification')
    parsed = ComponentQueryService._parse_tool_invoke_result(SimpleNamespace(name='web_search', plugin_id='local.daifeilong'), returned)
    assert parsed.success and job['result']['text'] in parsed.get_history_content()
    reply = await LLMOrchestrator('replyer', request_type='deployment.cached_search_reply').generate_response_async(
        '遵循以下当前人设及说话长度要求：\n' + persona + '\n当前会话补充要求：\n' + reply_rules + '\n内部回复测试，不向平台发送。历史答复说原帖无法核实。现在用户再次要求查询该人物近期动态，本次新查询：' + job.get('prompt', '') + ('\n用户还明确要求：请给我最相关的原文链接。' if want_links else '') + '\n本次工具结果：\n' + parsed.get_history_content(), max_tokens=1800)
    links = re.findall(r'https?://[^\s<>()\[\]，。]+', job['result']['text'])
    source_present = any(link in reply.response for link in links)
    limit_preserved = not ('403' in job['result']['text']) or bool(re.search(r'403|未.{0,10}核|无法.{0,10}核|访问受限', reply.response))
    has_summary = any(word in reply.response for word in ('网络安全', '图像', 'Cat Wu', '产品'))
    outcome = {'model': reply.model_name, 'scope': scope, 'links_requested': want_links, 'reply': reply.response, 'source_url_present': source_present, 'limitation_preserved': limit_preserved, 'useful_summary_present': has_summary, 'host_parser_used': True, 'new_search': False, 'qq_messages_sent': 0}
    Path('/MaiMBot/data/verification/search-reply-probe-' + scope + ('-links' if want_links else '') + '.json').write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
    print(json.dumps(outcome, ensure_ascii=False))
    if not ((source_present or not want_links) and limit_preserved and has_summary):
        raise RuntimeError('Reply omitted source, useful summary or verification caveat')
asyncio.run(main())
