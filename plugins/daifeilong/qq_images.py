"""Recover native QQ references that are missing from the live chat context."""

import asyncio
import io
import re
from urllib.parse import urlsplit

import aiohttp
import httpx
from PIL import Image

from .media import ImageError, MAX_REFERENCE_ATTACHMENTS


MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
QQ_IMAGE_HOSTS = {'multimedia.nt.qq.com.cn', 'gchat.qpic.cn', 'c2cpicdw.qpic.cn'}
IMAGE_EXTENSIONS = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}


def reference_picture(raw: bytes, index: int) -> tuple[str, bytes]:
    if len(raw) > MAX_BYTES:
        raise ImageError('原图超过 10 MiB')
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > MAX_PIXELS:
            raise ImageError('引用图片像素超过上限')
        if image.format == 'GIF':
            # The drawing backend accepts static input images. Use the first frame.
            buffer = io.BytesIO()
            image.convert('RGBA').save(buffer, format='PNG')
            raw = buffer.getvalue()
            extension = '.png'
        else:
            extension = IMAGE_EXTENSIONS.get(image.format)
            if not extension:
                raise ImageError('引用图片的格式不受支持')
            image.verify()
    if len(raw) > MAX_BYTES:
        raise ImageError('原图超过 10 MiB')
    name = 'original' if index == 1 else f'original-{index}'
    return name + extension, raw


async def napcat_message(token: str, message_id: str) -> dict:
    async with aiohttp.ClientSession(
        headers={'Authorization': 'Bearer ' + token},
        timeout=aiohttp.ClientTimeout(total=5),
    ) as client:
        async with client.ws_connect('http://napcat:3001', max_msg_size=2 * 1024 * 1024) as socket:
            await socket.send_json({'action': 'get_msg', 'params': {'message_id': int(message_id)}, 'echo': message_id})
            while True:
                result = await socket.receive_json()
                if result.get('echo') == message_id:
                    return (result.get('data') or {}) if result.get('status') == 'ok' else {}


async def download_picture(client: httpx.AsyncClient, url: str, limit: int) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != 'https' or parsed.hostname not in QQ_IMAGE_HOSTS or parsed.username
        or parsed.password or parsed.port not in (None, 443)
    ):
        raise ImageError('引用图片没有可用的 QQ 下载地址')
    async with client.stream('GET', url, follow_redirects=False) as response:
        response.raise_for_status()
        announced = response.headers.get('content-length', '')
        if announced.isdecimal() and int(announced) > limit:
            raise ImageError('引用图片合计超过 10 MiB')
        result = bytearray()
        async for chunk in response.aiter_bytes():
            result.extend(chunk)
            if len(result) > limit:
                raise ImageError('引用图片合计超过 10 MiB')
    return bytes(result)


async def read_group_images(token: str, group_id: str, message_id: str) -> list[tuple[str, bytes]]:
    if not token or not group_id.isdecimal() or not re.fullmatch(r'-?[0-9]{1,12}', message_id):
        return []
    try:
        async with asyncio.timeout(9):
            message = await napcat_message(token, message_id)
            if str(message.get('group_id') or '') != group_id:
                return []
            if str(message.get('message_id') or '') != message_id:
                return []
            segments = [part['data'] for part in message.get('message') or [] if part.get('type') == 'image']
            if len(segments) > MAX_REFERENCE_ATTACHMENTS:
                raise ImageError(f'引用消息图片超过 {MAX_REFERENCE_ATTACHMENTS} 张')
            pictures = []
            remaining = MAX_BYTES
            if segments:
                async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                    for index, segment in enumerate(segments, 1):
                        raw = await download_picture(client, segment.get('url') or '', remaining)
                        picture = await asyncio.to_thread(reference_picture, raw, index)
                        remaining -= len(picture[1])
                        if remaining < 0:
                            raise ImageError('引用图片合计超过 10 MiB')
                        pictures.append(picture)
            return pictures
    except (aiohttp.ClientError, httpx.HTTPError, TimeoutError, OSError, TypeError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError('暂时无法从 QQ 读取引用原图') from exc
