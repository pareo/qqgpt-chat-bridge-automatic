"""Replay a completed task through the plugin/Host boundary without QQ sends."""
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx

sys.path.insert(0, '/project/plugins')
sys.path.insert(0, '/MaiMBot')
os.environ['MAIBOT_SHARED_MODEL_CATALOG'] = '/MaiMBot/host/model_catalog.toml'
from daifeilong.plugin import DaifeilongPlugin
from src.plugin_runtime.component_query import ComponentQueryService

async def main():
    task_id = sys.argv[1]
    directory = Path('/project/config/local')
    credentials = json.loads((directory / 'secrets.json').read_text(encoding='utf-8-sig'))
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        response = await client.get('http://codex-worker:18121/v1/tasks/' + task_id, headers={'Authorization': 'Bearer ' + credentials['agent_worker_token']})
        response.raise_for_status()
        job = response.json()
    assert job['state'] == 'succeeded'
    original = job['result']['text']
    plugin = DaifeilongPlugin()
    plugin.set_plugin_config({})
    plugin.directory = directory
    with patch('daifeilong.desktop.run_task', new=AsyncMock(return_value={'id': task_id, 'text': original, 'artifacts': []})):
        returned = await plugin.web_search('completed-task replay', stream_id='verification-only')
    parsed = ComponentQueryService._parse_tool_invoke_result(SimpleNamespace(name='web_search', plugin_id='local.daifeilong'), returned)
    assert parsed.success and original in parsed.content and 'https://' in parsed.content
    evidence = {'task_id': task_id, 'host_content_matches_complete_result': True, 'content_characters': len(parsed.content), 'source_links_present': True, 'new_search_submitted': False, 'qq_messages_sent': 0}
    Path('/MaiMBot/data/verification/search-tool-content.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence))

asyncio.run(main())
