"""Authenticated, bounded task client. No QQ transport or GUI operations."""
import asyncio
import base64
import hashlib
import io
import time
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from PIL import Image
from .media import ImageError, reference_files

class DesktopError(ImageError):
    pass

def enabled(config):
    return bool(config.get('desktop_worker', {}).get('enabled'))

def reference_images(directory, characters, prompt, kind, names, originals):
    if kind == 'casual_sticker' and not names.strip():
        names = 'gpt'
    refs = list(originals) + reference_files(directory, characters, names)
    if len(refs) > 4:
        raise DesktopError('一次最多上传4张原图及角色参考图')
    if names.strip():
        prompt += '\n角色外观以附图为准，不复制介绍文字：\n' + '\n'.join(characters[k.strip()]['appearance'] for k in names.split(',') if k.strip())
    return prompt, refs

async def run_task(config, credentials, kind, prompt, images=(), *, client=None, poll_seconds=.7):
    worker = config.get('desktop_worker', {})
    if not enabled(config):
        raise DesktopError('ChatGPT任务服务未启用')
    token = credentials.get('desktop_worker_token', '')
    if len(token) < 32:
        raise DesktopError('ChatGPT任务服务令牌未配置')
    base = worker.get('url', 'http://host.docker.internal:18120').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise DesktopError('任务地址须为不含路径和凭据的HTTP(S)地址')
    if kind not in ('search', 'image', 'sticker') or not prompt.strip() or len(prompt) > 18000 or len(images) > 4:
        raise DesktopError('任务类型、提示词或参考图数量不合法')
    task_id = uuid4().hex
    payload = {'id': task_id, 'kind': kind, 'prompt': prompt, 'images': []}
    for _, raw in images:
        if len(raw) > 10 * 1024 * 1024:
            raise DesktopError('参考图片超过10 MiB')
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 40000000:
                raise DesktopError('参考图片像素过大')
            image.verify()
        payload['images'].append({'base64': base64.b64encode(raw).decode()})
    owned = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False)
    headers = {'Authorization': 'Bearer ' + token}
    try:
        # Never repeat a lost POST. Its durable ID permits later inspection.
        response = await client.post(base + '/v1/tasks', headers=headers, json=payload)
        if response.status_code != 202:
            raise DesktopError(f'任务被拒绝（HTTP {response.status_code}）；任务 {task_id}')
        job, errors = response.json(), 0
        deadline = time.monotonic() + min(540, worker.get('timeout_seconds', 240) + worker.get('queue_wait_seconds', 60))
        while job.get('state') not in ('succeeded', 'failed', 'uncertain'):
            if time.monotonic() >= deadline:
                raise DesktopError(f'等待超时，可能仍执行，未重复提交；任务 {task_id}')
            await asyncio.sleep(poll_seconds)
            try:
                response = await client.get(base + '/v1/tasks/' + task_id, headers=headers)
                response.raise_for_status()
                job, errors = response.json(), 0
            except httpx.HTTPError:
                errors += 1
                if errors > 2:
                    raise DesktopError(f'状态读取失败，未重新提问；任务 {task_id}') from None
        if job.get('id') != task_id:
            raise DesktopError('任务归属不匹配，未转发')
        if job['state'] != 'succeeded':
            raise DesktopError(f'任务失败或结果待确认，未自动重提；任务 {task_id}')
        result = job.get('result', {})
        if len(result.get('artifacts', [])) > 8:
            raise DesktopError('生成附件数量超过上限')
        artifacts = []
        for artifact in result.get('artifacts', []):
            aid = str(artifact.get('id', ''))
            if not aid or not all(c in '0123456789abcdef-' for c in aid):
                raise DesktopError('附件标识不合法')
            limit = (20 if artifact.get('kind') == 'image' else 10) * 1024 * 1024
            expected = artifact.get('bytes', 0)
            if not isinstance(expected, int) or not 0 < expected <= limit:
                raise DesktopError('生成附件大小超限')
            raw = bytearray()
            async with client.stream('GET', base + '/v1/tasks/' + task_id + '/artifacts/' + aid, headers=headers) as download:
                download.raise_for_status()
                async for chunk in download.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise DesktopError('附件实际大小超限')
            if len(raw) != expected or hashlib.sha256(raw).hexdigest() != artifact.get('sha256'):
                raise DesktopError('附件校验失败，未发送')
            if artifact.get('kind') == 'image':
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 40000000:
                        raise DesktopError('生成图片像素过大')
                    image.verify()
            elif artifact.get('kind') != 'file':
                raise DesktopError('生成附件类型未知')
            artifacts.append({**artifact, 'raw': bytes(raw)})
        if kind != 'search' and not any(a['kind'] == 'image' for a in artifacts):
            raise DesktopError('未取得生成图片，未将文字当作生图成功')
        return {'id': task_id, 'text': str(result.get('text', '')), 'artifacts': artifacts}
    except httpx.HTTPError:
        raise DesktopError(f'连接异常，提交情况需核查，未自动重提；任务 {task_id}') from None
    except (ValueError, KeyError, TypeError):
        raise DesktopError(f'响应无法读取，未重复执行；任务 {task_id}') from None
    finally:
        if owned:
            await client.aclose()
