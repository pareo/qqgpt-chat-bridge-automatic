"""Explicit API probes. Never sends messages to QQ; never prints credentials."""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import sys
import time

import httpx

sys.path.insert(0, '/MaiMBot')
os.environ['MAIBOT_SHARED_MODEL_CATALOG'] = '/MaiMBot/host/model_catalog.toml'
DIRECTORY = Path('/project/config/local')


def load(name):
    return json.loads((DIRECTORY / name).read_text(encoding='utf-8-sig'))


async def main(action):
    config, credentials = load('project.json'), load('secrets.json')
    if action == 'image-generate':
        from unittest.mock import patch
        sys.path.insert(0, '/project/plugins')
        from daifeilong import media
        config['images'].update(enabled=True, model=config['images']['model'] or 'gpt-image-2')
        started = time.monotonic()
        with patch('daifeilong.media.read_settings', return_value=(config, credentials, load('characters.json'))):
            raw = await asyncio.to_thread(media.generate, DIRECTORY, 'API connection test image: a single blue circle on a plain white background. No text.', 'image', '')
        destination = Path('/MaiMBot/data/verification/image-api.png')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        print(json.dumps({'image_success': True, 'seconds': round(time.monotonic() - started, 2), 'bytes': len(raw), 'model': config['images']['model'], 'output': str(destination)}))
        return
    if action == 'image-models':
        url = (config['images']['base_url'] or config['api']['base_url']).rstrip('/') + '/models'
        key = credentials['image_api_key'] or credentials['sub2api_api_key']
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.get(url, headers={'Authorization': 'Bearer ' + key})
        print('Image credential model discovery HTTP', response.status_code)
        if response.is_success:
            print(json.dumps([item['id'] for item in response.json().get('data', [])], ensure_ascii=False))
        return
    if action == 'image-route':
        url = (config['images']['base_url'] or config['api']['base_url']).rstrip('/') + '/images/generations'
        key = credentials['image_api_key'] or credentials['sub2api_api_key']
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.post(url, headers={'Authorization': 'Bearer ' + key}, json={})
        try:
            error = response.json().get('error', {})
            if not isinstance(error, dict):
                error = {'message': str(error)}
            message = str(error.get('message', ''))
            for value in credentials.values():
                if value:
                    message = message.replace(value, '[redacted]')
            print(json.dumps({'status': response.status_code, 'type': error.get('type', ''), 'message': message[:500]}, ensure_ascii=False))
        except ValueError:
            print('Image route HTTP', response.status_code, '(non-JSON response)')
        return
    if action in ('qq-status', 'qq-group', 'qq-history'):
        import aiohttp
        try:
            async with aiohttp.ClientSession(headers={'Authorization': 'Bearer ' + credentials['onebot_token']}, timeout=aiohttp.ClientTimeout(total=6)) as client:
                async with client.ws_connect('http://napcat:3001') as socket:
                    operation = {'qq-group': 'get_group_info', 'qq-history': 'get_group_msg_history'}.get(action, 'get_login_info')
                    params = {'group_id': int(config['groups'][0]['id'])} if action != 'qq-status' else {}
                    if action == 'qq-history':
                        params['count'] = 20
                    await socket.send_json({'action': operation, 'params': params, 'echo': 'daifeilong-status'})
                    async for event in socket:
                        if event.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(event.data)
                        if data.get('echo') == 'daifeilong-status':
                            if action == 'qq-history':
                                messages = (data.get('data') or {}).get('messages', [])
                                summary = [{'message_id': item.get('message_id'), 'time': item.get('time'), 'self': str(item.get('user_id')) == config['bot']['account'], 'segments': [{'type': part.get('type'), 'text': part.get('data', {}).get('text', '')} for part in item.get('message', []) if isinstance(part, dict)]} for item in messages[-20:]]
                                print(json.dumps({'success': data.get('status') == 'ok', 'messages': summary}, ensure_ascii=False))
                                return
                            if action == 'qq-group':
                                group = data.get('data') or {}
                                print(json.dumps({'success': data.get('status') == 'ok', 'group_id': group.get('group_id'), 'group_name': group.get('group_name'), 'member_count': group.get('member_count')}, ensure_ascii=False))
                                return
                            account = str(data.get('data', {}).get('user_id', ''))
                            print(json.dumps({'connected': data.get('status') == 'ok', 'account_matches': account == config['bot']['account']}, ensure_ascii=False))
                            return
        except (aiohttp.ClientError, asyncio.TimeoutError):
            print('QQ not ready: waiting for phone login or OneBot startup')
        return
    from src.llm_models.utils_model import LLMOrchestrator
    started = time.monotonic()
    request = LLMOrchestrator('vlm' if action == 'vision' else 'replyer', request_type='deployment.smoke')
    if action == 'chat':
        result = await request.generate_response_async('这是一项接口连通性测试。只回复：连接成功', max_tokens=1024)
    elif action == 'tools':
        tools = [{'type': 'function', 'function': {'name': 'connection_test', 'description': '接口测试，必须调用一次此函数确认连接', 'parameters': {'type': 'object', 'properties': {'status': {'type': 'string'}}, 'required': ['status'], 'additionalProperties': False}}}]
        result = await request.generate_response_async('不要输出正文。请调用 connection_test，status 填 ok。', max_tokens=1024, tools=tools, force_stream_mode=True)
    elif action == 'vision':
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (256, 128), 'red')
        ImageDraw.Draw(image).rectangle((128, 0, 255, 127), fill='blue')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        result = await request.generate_response_for_image('这张图左右两边各是什么颜色？只用中文简短回答。', base64.b64encode(buffer.getvalue()).decode(), 'png', max_tokens=1024)
    else:
        raise ValueError('Unsupported probe')
    summary = {'action': action, 'seconds': round(time.monotonic() - started, 2), 'model': result.model_name,
               'reply': result.response[:300], 'tool_calls': [call.func_name for call in result.tool_calls or []], 'tokens': result.total_tokens}
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('chat', 'tools', 'vision', 'image-models', 'image-route', 'image-generate', 'qq-status', 'qq-group', 'qq-history'))
    args = parser.parse_args()
    try:
        asyncio.run(main(args.action))
    except Exception as exc:
        message = str(exc)
        for value in load('secrets.json').values():
            if value:
                message = message.replace(value, '[redacted]')
        print(type(exc).__name__ + ': ' + message[:1200], file=sys.stderr)
        sys.exit(1)
