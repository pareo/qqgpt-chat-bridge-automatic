"""MaiBot extension; transport and conversational decisions remain native."""
from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
import random
import re
import time
from uuid import uuid4

from maibot_sdk import Command, Field, HookHandler, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .media import ImageError, generate, read_settings, sticker_png, table_html
from . import desktop
from .search_result import search_content
from .reply_evidence import ReplyEvidence


class PluginSection(PluginConfigBase):
    enabled: bool = Field(default=True, description='启用大肥龙扩展')
    config_version: str = Field(default='1.0.0', description='配置版本')


class Reactions(PluginConfigBase):
    __ui_label__ = '闲聊配图'
    probability: float = Field(default=0.8, ge=0, le=1, description='闲聊表情概率；普通生图不受影响', json_schema_extra={'x-widget': 'select', 'options': [0, 0.1, 0.3, 0.5, 0.8, 1]})
    cooldown_seconds: int = Field(default=10, ge=0, le=3600, description='闲聊表情冷却秒数')


class Config(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    reactions: Reactions = Field(default_factory=Reactions)


def sent_ok(result) -> bool:
    return result is True or (isinstance(result, dict) and result.get('sent') is True)


class DaifeilongPlugin(MaiBotPlugin):
    config_model = Config

    async def on_load(self) -> None:
        self.directory = Path(os.environ.get('DAIFEILONG_CONFIG_DIR', '/project/config/local'))
        self.last_casual = {}
        self.image_locks = {}
        self.reply_evidence = ReplyEvidence()
        self.ctx.logger.info('大肥龙扩展已加载：模式切换、生图和表格图片')

    async def on_unload(self) -> None:
        pass

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        pass

    @HookHandler('maisaka.planner.before_request', name='capture_current_tool_evidence')
    async def capture_current_tool_evidence(self, session_id='', items=None, **kwargs):
        self.reply_evidence.capture(session_id, items or [])
        return {'action': 'continue'}

    @HookHandler('maisaka.replyer.before_request', name='supply_current_tool_evidence')
    async def supply_current_tool_evidence(self, session_id='', reply_message_id='', extra_prompt='', **kwargs):
        prompt = self.reply_evidence.prompt(session_id, reply_message_id, extra_prompt)
        if prompt is None:
            return {'action': 'continue'}
        self.ctx.logger.info('已将当前消息的检索正文与来源交给Replyer')
        return {'action': 'continue', 'modified_kwargs': {'extra_prompt': prompt}}

    @Tool('ask_codex', timeout_ms=600000, description='将需要深入分析的任务交给隔离的Codex后端，普通闲聊继续由当前模型回复。结果待确认时不得重复提交。', parameters=[ToolParameterInfo(name='question', param_type=ToolParamType.STRING, description='完整问题与必要上下文', required=True)])
    async def ask_codex(self, question: str, stream_id: str = '', **kwargs):
        if not stream_id:
            return {'success': False, 'error': '缺少来源会话'}
        try:
            config, credentials, _ = await asyncio.to_thread(read_settings, self.directory)
            if not config.get('agent_worker', {}).get('enabled'):
                return {'success': False, 'error': 'Codex 后端尚未通过验收或未启用'}
            result = await desktop.run_task(config, credentials, 'chat', question)
            return {'success': True, 'task_id': result['id'], 'content': result['text'], 'text': result['text']}
        except ImageError as exc:
            return {'success': False, 'error': str(exc), 'message': '据实说明结果，不重复提交'}

    @Tool('web_search', timeout_ms=600000, description='需要最新消息、联网检索、核实资料或来源时调用。结果是内部参考资料，须按当前人设提炼信息回答，不直接转发网页或链接列表；用户要原文或链接时按需提供。普通闲聊不调用；失败或待确认时不重复提交。', parameters=[ToolParameterInfo(name='query', param_type=ToolParamType.STRING, description='搜索问题，包含必要的时间、地点和背景', required=True)])
    async def web_search(self, query: str, stream_id: str = '', **kwargs):
        if not stream_id:
            return {'success': False, 'error': '缺少来源聊天'}
        try:
            config, credentials, _ = await asyncio.to_thread(read_settings, self.directory)
            started = time.monotonic()
            result = await desktop.run_task(config, credentials, 'search', query)
            self.ctx.logger.info(f'联网检索完成：{time.monotonic()-started:.1f}s，资料{len(result["text"])}字')
            return {'success': True, 'task_id': result['id'], 'content': search_content(result['text']), 'text': result['text'], 'message': '按当前人设提炼检索信息回答，勿直接转发网页或堆链接；保留核验限制，链接按需提供，不重复发起同一搜索。'}
        except ImageError as exc:
            return {'success': False, 'error': str(exc), 'message': '据实说明失败或待确认，不伪造来源，不重复发起。'}

    @Command('daifeilong_mode', description='查看或切换大肥龙模式，群内任何人可用；当前为全局模式', pattern=r'^/模式(?:\s+(?P<mode>.+?))?\s*$', intercept_message_level=1)
    async def switch_mode(self, stream_id: str = '', **kwargs):
        content = str(kwargs.get('message', '') or kwargs.get('content', ''))
        if not isinstance(kwargs.get('message', ''), str):
            content = str(kwargs.get('message', {}).get('plain_text', '') or kwargs.get('content', ''))
        # Runner supplies regex captures as matched_groups, not positional arguments.
        captures = kwargs.get('matched_groups', {})
        name = str(captures.get('mode', '')).strip() if isinstance(captures, dict) else ''
        match = re.search(r'/模式\s+(.+?)\s*$', content)
        if not name and match:
            name = match.group(1)
        if not name:
            current = await self.ctx.personality.get_current()
            profiles = await self.ctx.personality.list()
            return await self.ctx.send.text('当前模式：' + current.get('name', '未命名') + '；可选：' + '、'.join(profile['name'] for profile in profiles['profiles']), stream_id)
        profiles = await self.ctx.personality.list()
        if name not in {profile['name'] for profile in profiles['profiles']}:
            return await self.ctx.send.text('没有这个模式，可选：' + '、'.join(profile['name'] for profile in profiles['profiles']), stream_id)
        await self.ctx.personality.switch(name)
        return await self.ctx.send.text('已切换到' + name, stream_id)

    @Tool('generate_image', timeout_ms=600000, description='生成图片并直接发到当前聊天。用户生图/改图/续画用kind=image，明确制作表情包用sticker；只有非作图的日常闲聊才用casual_sticker（会检查概率和冷却）。普通图不受表情包规则影响。角色外观通过参考图约束，不能声称生成了但只返回文字。',
          parameters=[ToolParameterInfo(name='prompt', param_type=ToolParamType.STRING, description='完整绘图要求，保留用户主题', required=True),
                      ToolParameterInfo(name='kind', param_type=ToolParamType.STRING, description='image / sticker / casual_sticker', required=True),
                      ToolParameterInfo(name='characters', param_type=ToolParamType.STRING, description='需要参考的人设ID，逗号分隔：gpt,deepseek,gemini,grok,claude,zcode,minimax,glm,qwen。普通作图不强加人设，可为空', required=False),
                      ToolParameterInfo(name='source_image_id', param_type=ToolParamType.STRING, description='改图/续画时必填当前上下文原图的消息编号或工具媒体引用，不得凭空编造；无需改图时留空', required=False)])
    async def generate_image(self, prompt: str, kind: str = 'image', characters: str = '', source_image_id: str = '', stream_id: str = '', **kwargs):
        if not stream_id:
            return {'success': False, 'error': '缺少来源聊天，未生成或发送'}
        config, credentials, characters_data = await asyncio.to_thread(read_settings, self.directory)
        if kind not in ('image', 'sticker', 'casual_sticker'):
            return {'success': False, 'error': '未知图片类型'}
        use_desktop = config.get('images', {}).get('backend', 'api') in ('desktop', 'codex-acp')
        if kind == 'casual_sticker':
            if not (desktop.enabled(config) if use_desktop else config['images']['enabled']):
                return {'success': True, 'skipped': True, 'message': '当前生图未启用，只用文字接话，不向群里报错'}
            now = time.monotonic()
            if now - self.last_casual.get(stream_id, -1e9) < self.config.reactions.cooldown_seconds or random.random() >= self.config.reactions.probability:
                return {'success': True, 'skipped': True, 'message': '本轮不配表情，正常文字接话即可'}
        lock = self.image_locks.setdefault(stream_id, asyncio.Lock())
        if lock.locked():
            return {'success': False, 'message': '该聊天已有生图任务，未重复提交'}
        async with lock:
            try:
                originals = []
                if source_image_id:
                    resolved = await self.ctx.maisaka.context.resolve_image(stream_id, source_image_id)
                    image = resolved.get('image', {})
                    if not resolved.get('success') or not image.get('binary_data_base64'):
                        raise ImageError('无法读取当前聊天中的原图，未用文字猜测代替改图')
                    original = base64.b64decode(image['binary_data_base64'], validate=True)
                    if len(original) > 10 * 1024 * 1024:
                        raise ImageError('改图原图超过10 MiB')
                    originals.append(('original.png', original))
                if use_desktop:
                    desktop_prompt, references = await asyncio.to_thread(desktop.reference_images, self.directory, characters_data, prompt, kind, characters, originals)
                    result = await desktop.run_task(config, credentials, 'image' if kind == 'image' else 'sticker', desktop_prompt, references)
                    return await self.deliver_desktop_images(result, kind, stream_id)
                raw = await asyncio.to_thread(generate, self.directory, prompt, kind, characters, originals)
                # Preserve output before attempting QQ delivery, including uncertain sends.
                cache_id = uuid4().hex
                cache_dir = self.ctx.paths.data_dir / 'generated'
                await asyncio.to_thread(cache_dir.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread((cache_dir / (cache_id + '.image')).write_bytes, raw)
                result = await self.ctx.send.image(base64.b64encode(raw).decode(), stream_id, return_details=True)
                if not sent_ok(result):
                    return {'success': False, 'cache_id': cache_id, 'message': '图片已生成并缓存，但QQ发送未确认；未重复发送'}
                if kind == 'casual_sticker':
                    self.last_casual[stream_id] = time.monotonic()
                return {'success': True, 'sent': True, 'cache_id': cache_id, 'message_id': result.get('message_id') if isinstance(result, dict) else None}
            except Exception as exc:
                message = str(exc) if isinstance(exc, ImageError) else '图片处理发生异常，请查看扩展日志'
                self.ctx.logger.error('生图步骤失败：' + type(exc).__name__)
                await self.ctx.send.text('生图失败：' + message, stream_id)
                return {'success': False, 'reported_to_chat': True, 'error': message}

    async def deliver_desktop_images(self, result, kind, stream_id):
        cache = self.ctx.paths.data_dir / 'desktop' / result['id']
        await asyncio.to_thread(cache.mkdir, parents=True, exist_ok=True)
        saved = []
        for artifact in result['artifacts']:
            raw = sticker_png(artifact['raw']) if artifact['kind'] == 'image' and kind != 'image' else artifact['raw']
            path = cache / (artifact['id'] + ('.png' if artifact['kind'] == 'image' else '.file'))
            await asyncio.to_thread(path.write_bytes, raw)
            saved.append((artifact, raw, path))
        sent_count = 0
        try:
            for artifact, raw, path in saved:
                if artifact['kind'] == 'image':
                    delivered = await self.ctx.send.image(base64.b64encode(raw).decode(), stream_id, return_details=True)
                    confirmed = sent_ok(delivered)
                else:
                    uploaded = await self.ctx.files.upload(path, name=artifact['name'])
                    delivered = await self.ctx.files.send(uploaded['file_ref'])
                    confirmed = delivered.get('status') == 'sent'
                if not confirmed:
                    return {'success': False, 'task_id': result['id'], 'sent_count': sent_count, 'error': 'QQ投递未确认，已缓存全部附件；不要重发生图任务或已发附件'}
                sent_count += 1
            if result['text'] and not sent_ok(await self.ctx.send.text(result['text'], stream_id)):
                return {'success': False, 'task_id': result['id'], 'sent_count': sent_count, 'error': '附件已发，附带文字发送未确认；不要重发'}
            if kind == 'casual_sticker':
                self.last_casual[stream_id] = time.monotonic()
            return {'success': True, 'sent': True, 'task_id': result['id'], 'sent_count': sent_count, 'message': '生成附件及附带文字已发送，不要重复。'}
        except Exception:
            self.ctx.logger.error('桌面任务投递失败，缓存保留：' + result['id'])
            return {'success': False, 'task_id': result['id'], 'sent_count': sent_count, 'error': '附件已缓存，投递异常；不要重新生成或重复发送'}

    @Tool('render_table', description='将表格排版为清楚的图片并直接发送，避免QQ纯文本串列。只用于实际表格，正文无需调用。', parameters=[ToolParameterInfo(name='markdown', param_type=ToolParamType.STRING, description='完整Markdown表格，保留表头及所有单元格', required=True)])
    async def render_table(self, markdown: str, stream_id: str = '', **kwargs):
        if not stream_id:
            return {'success': False, 'error': '缺少来源聊天'}
        try:
            rendered = await self.ctx.render.html2png(table_html(markdown), viewport={'width': 1100, 'height': 100}, device_scale_factor=1.0, full_page=True, allow_network=False)
            result = await self.ctx.send.image(rendered['image_base64'], stream_id, return_details=True)
            return {'success': sent_ok(result), 'sent': sent_ok(result)}
        except Exception as exc:
            self.ctx.logger.error('表格渲染失败：' + type(exc).__name__)
            # Preserve the data without flattening columns into one line.
            await self.ctx.send.text('表格图片暂时无法生成，保留原始表格：\n' + markdown, stream_id)
            return {'success': False, 'reported_to_chat': True, 'error': '表格渲染失败，已保留原文'}


def create_plugin():
    return DaifeilongPlugin()
