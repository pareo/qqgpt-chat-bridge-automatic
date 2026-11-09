"""Render a fixture locally. Never connects to QQ or calls a model."""
import asyncio
import base64
import os
from pathlib import Path
import sys

sys.path.insert(0, '/project/plugins')
sys.path.insert(0, '/MaiMBot')
os.environ['MAIBOT_SHARED_MODEL_CATALOG'] = '/MaiMBot/host/model_catalog.toml'
from daifeilong.media import table_html
from src.services.html_render_service import get_html_render_service, HtmlRenderRequest


async def main():
    service = get_html_render_service()
    result = await service.render_html_to_png(HtmlRenderRequest(
        html=table_html('| 项目 | 结果 | 说明 |\n|---|---|---|\n| 图片 | 支持 | 保持角色参考图 |\n| 文件 | 10 MiB | 超限跳过并提示 |\n| 模型 | 可修改 | 不依赖桌面窗口 |'),
        viewport_width=1000, viewport_height=100, full_page=True,
        device_scale_factor=1.0, timeout_ms=60000, allow_network=False))
    target = Path('/MaiMBot/data/verification/table.png')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(result.image_base64))
    print(f'Table rendered: {result.width}x{result.height}; {target}')
    await service.reset_browser(restart_playwright=True)


if __name__ == '__main__':
    asyncio.run(main())
