"""Explicit real-model checks; never sends QQ messages or changes routing."""
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx

root = Path('/project')
config = json.loads((root / 'config/local/project.json').read_text(encoding='utf-8-sig'))['agent_worker']
config['token'] = json.loads((root / 'config/local/secrets.json').read_text(encoding='utf-8-sig'))['agent_worker_token']
async def main():
    evidence = []
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        for kind, prompt in [('chat', '仅回复 DFL_CODEX_OK，不要调用工具。'), ('search', '必须实际搜索网页，仅查找 OpenAI 官方 Codex App Server 文档，简短说它支持什么并给出来源完整URL。'), ('image', '生成一张简单的蓝色圆形图标，白色背景，无文字。必须实际生图。')]:
            task_id = uuid4().hex
            start = time.monotonic()
            headers = {'Authorization': 'Bearer ' + config['token']}
            response = await client.post('http://codex-worker:18121/v1/tasks', headers=headers, json={'id': task_id, 'kind': kind, 'prompt': prompt})
            response.raise_for_status()
            job = response.json()
            deadline = time.monotonic() + 280
            while job.get('state') not in ('succeeded', 'failed', 'uncertain') and time.monotonic() < deadline:
                await asyncio.sleep(1)
                job = (await client.get('http://codex-worker:18121/v1/tasks/' + task_id, headers=headers)).json()
            result = job.get('result', {})
            item = {'kind': kind, 'id': task_id, 'state': job.get('state'), 'seconds': round(time.monotonic()-start, 2), 'text': result.get('text', '')[:1000], 'tool_events': result.get('tool_events', []), 'artifacts': result.get('artifacts', []), 'error': job.get('error', '')}
            evidence.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)
            destination = Path('/MaiMBot/data/verification/codex-probe.json')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
            if job.get('state') != 'succeeded':
                break
asyncio.run(main())
