"""Image API client and readable table formatting; no QQ side effects."""
from __future__ import annotations

import base64
from html import escape
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps


class ImageError(RuntimeError):
    pass


def read_settings(directory: Path) -> tuple[dict, dict, dict]:
    def load(name):
        return json.loads((directory / name).read_text(encoding='utf-8-sig'))
    return load('project.json'), load('secrets.json'), load('characters.json')


def reference_files(directory: Path, characters: dict, names: str) -> list[tuple[str, bytes]]:
    result = []
    root = directory.resolve()
    for identifier in dict.fromkeys(part.strip() for part in names.split(',') if part.strip()):
        if identifier not in characters:
            raise ImageError(f'未知角色 {identifier}，可选：' + ', '.join(characters))
        path = (root / characters[identifier]['reference']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ImageError(f'角色参考图不可读取：{identifier}')
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ImageError(f'角色参考图超过10 MiB：{identifier}')
        result.append((path.name, path.read_bytes()))
    if len(result) > 4:
        raise ImageError('单次最多附加4张角色参考图')
    return result


def sticker_png(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as original:
        image = ImageOps.contain(original.convert('RGBA'), (300, 300))
        canvas = Image.new('RGBA', (300, 300), (255, 255, 255, 0))
        canvas.alpha_composite(image, ((300-image.width)//2, (300-image.height)//2))
        target = io.BytesIO()
        canvas.save(target, format='PNG', dpi=(96, 96))
        return target.getvalue()


def public_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        return False
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    return bool(addresses) and all(ipaddress.ip_address(record[4][0]).is_global for record in addresses)


def generate(directory: Path, prompt: str, kind: str, names: str, source_images: list[tuple[str, bytes]] | None = None) -> bytes:
    config, credentials, characters = read_settings(directory)
    image_config = config['images']
    if not image_config['enabled'] or not image_config['model']:
        raise ImageError('生图尚未启用，请配置生图模型和接口')
    if kind not in ('image', 'sticker', 'casual_sticker'):
        raise ImageError('图片类型必须为 image、sticker 或 casual_sticker')
    if not prompt.strip() or len(prompt) > 16000:
        raise ImageError('图片提示词为空或过长')
    if kind == 'casual_sticker' and not names.strip():
        names = 'gpt'
    refs = list(source_images or []) + reference_files(directory, characters, names)
    if len(refs) > 4:
        raise ImageError('单次最多附加4张原图和角色参考图')
    if names.strip():
        descriptions = [characters[key.strip()]['appearance'] for key in names.split(',') if key.strip()]
        prompt += '\n严格以所附参考图的角色外观为准，保留辨识特征，不复制图中介绍文字。\n' + '\n'.join(descriptions)
    if kind != 'image':
        prompt += '\n制作单张抽象搞笑的聊天反应表情，正方形构图，角色清楚可辨，避免细小文字。'
    base_url = (image_config['base_url'] or config['api']['base_url']).rstrip('/')
    key = credentials['image_api_key'] or credentials['sub2api_api_key']
    if not key:
        raise ImageError('未填写生图 API Key')
    fields = {'model': image_config['model'], 'prompt': prompt, 'size': image_config['size'], 'quality': image_config['quality']}
    max_bytes = image_config['max_output_mib'] * 1024 * 1024
    try:
        with httpx.Client(timeout=httpx.Timeout(image_config['timeout_seconds'], connect=15), follow_redirects=False, trust_env=False) as client:
            # A timed-out generation may still be running upstream: never blindly resubmit it.
            with client.stream('POST', base_url + ('/images/edits' if refs else '/images/generations'),
                headers={'Authorization': 'Bearer ' + key},
                **({'data': fields, 'files': [('image[]', (name, content, 'image/jpeg' if name.lower().endswith(('.jpg', '.jpeg')) else 'image/png')) for name, content in refs]} if refs else {'json': fields})) as response:
                if response.status_code != 200:
                    error_body = bytearray()
                    for chunk in response.iter_bytes():
                        error_body.extend(chunk)
                        if len(error_body) > 65536:
                            break
                    try:
                        error = json.loads(error_body).get('error', {})
                        detail = str(error.get('message', '')) if isinstance(error, dict) else str(error)
                    except (ValueError, AttributeError):
                        detail = ''
                    for secret in credentials.values():
                        if secret:
                            detail = detail.replace(secret, '[redacted]')
                    raise ImageError(f'图片接口返回 HTTP {response.status_code}：' + (detail[:300] or '检查模型、API分组与额度'))
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes * 2:
                        raise ImageError('图片接口响应超过大小上限')
            data = json.loads(body)
            outputs = data.get('data', [])
            if not outputs:
                raise ImageError('图片接口没有返回图片，不能将文字回复视为生图成功')
            item = outputs[0]
            if item.get('b64_json'):
                raw = base64.b64decode(item['b64_json'], validate=True)
            elif item.get('url'):
                if not public_url(item['url']):
                    raise ImageError('图片下载地址不是允许的公网地址')
                # No API Authorization header is sent to the image storage host.
                with client.stream('GET', item['url']) as response:
                    response.raise_for_status()
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > max_bytes:
                            raise ImageError('返回图片超过大小上限')
                    raw = bytes(chunks)
            else:
                raise ImageError('图片接口未返回可读取的图片数据')
    except httpx.TimeoutException:
        raise ImageError('生图接口超时，上游可能仍在生成；本次未自动重复生图') from None
    except (httpx.HTTPError, OSError):
        raise ImageError('生图接口连接或图片下载失败，请检查接口日志') from None
    except (ValueError, KeyError, TypeError):
        raise ImageError('生图接口返回格式无法读取') from None
    if len(raw) > max_bytes:
        raise ImageError('返回图片超过大小上限')
    with Image.open(io.BytesIO(raw)) as image:
        image.verify()
    return sticker_png(raw) if kind != 'image' else raw


def table_html(markdown: str) -> str:
    rows = []
    for line in markdown.strip().splitlines():
        if not line.strip():
            continue
        cells = re.split(r'(?<!\\)\|', line.strip().strip('|'))
        if all(re.fullmatch(r'\s*:?-{3,}:?\s*', cell) for cell in cells):
            continue
        rows.append([cell.strip().replace('\\|', '|') for cell in cells])
    if len(rows) < 2 or len(rows[0]) < 2:
        raise ValueError('需要至少两行、两列的 Markdown 表格')
    if len(rows) > 100 or len(rows[0]) > 12 or len(markdown) > 20000:
        raise ValueError('表格过大，请拆分或发送文件')
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError('表格各行列数不一致，请修正后发送')
    html_rows = []
    for index, row in enumerate(rows):
        tag = 'th' if index == 0 else 'td'
        html_rows.append('<tr>' + ''.join(f'<{tag}>{escape(cell)}</{tag}>' for cell in row) + '</tr>')
    return '<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:24px;background:#f6f7fb;font:17px sans-serif;color:#202530}table{border-collapse:collapse;background:white;width:100%;table-layout:fixed}td,th{border:1px solid #d9dfeb;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;text-align:left}th{background:#e9edff}tr:nth-child(odd) td{background:#f9faff}</style><table>' + ''.join(html_rows) + '</table>'
