"""Activate only verified capabilities; preserve all unrelated live settings."""
import json
from pathlib import Path
import shutil
import time
import tomlkit
from project import source_digest
from daifeilong.search_result import apply_reply_policy

root = Path('/project')
local = root / 'config/local'
generated = root / 'config/generated'
evidence = json.loads((root / 'data/core/verification/codex-probe.json').read_text())
checks = {item['kind']: item for item in evidence}
if checks.get('chat', {}).get('state') != 'succeeded' or checks.get('chat', {}).get('text', '').strip() != 'DFL_CODEX_OK':
    raise ValueError('Real Codex text verification missing')
search = checks.get('search', {})
if search.get('state') != 'succeeded' or not any(item.get('kind') == 'search' and item.get('status') == 'completed' for item in search.get('tool_events', [])):
    raise ValueError('Completed native search event required before activation')
images = checks.get('image', {})
image_ok = images.get('state') == 'succeeded' and bool(images.get('artifacts')) and images.get('artifacts_verified') is True
config_path = local / 'project.json'
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
backup = generated / 'backups' / ('codex-activate-' + str(time.time_ns()))
backup.mkdir(parents=True)
shutil.copyfile(config_path, backup / 'project.json')
bot_path = generated / 'core/bot_config.toml'
shutil.copyfile(bot_path, backup / 'bot_config.toml')
bot = tomlkit.parse(bot_path.read_text())
config['agent_worker'].update(enabled=True, capabilities={'chat': True, 'search': True, 'images': image_ok})
config['desktop_worker']['enabled'] = False
if image_ok:
    config['images']['backend'] = 'codex-acp'
reminder = '\n最新资料与联网核实调用 web_search，深入分析可调用 ask_codex；普通闲聊继续直接回答。工具失败须据实说明，不重复提交结果未知的任务。'
def extend(target):
    value = target.get('group_chat_prompt', '')
    if image_ok:
        value = value.replace('\n当前生图未启用：不要主动生成聊天表情；用户明确要求作图时说明暂不可用，不能声称已经完成。', '')
        if 'Codex图片任务已经验证启用' not in value:
            value += '\nCodex图片任务已经验证启用：明确生图、改图调用 generate_image，普通作图高质量，表情包才使用300×300规格。'
    if '深入分析可调用 ask_codex' not in value:
        value += reminder
    target['group_chat_prompt'] = value
extend(bot['chat']['reply_style'])
for profile in bot['personality'].get('profiles', []):
    extend(profile)
apply_reply_policy(bot)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
bot_path.write_text(tomlkit.dumps(bot))
(generated / 'source.json').write_text(json.dumps({'sha256': source_digest(), 'selective_update': 'verified-codex-backend'}) + '\n')
print(json.dumps({'activated': ['chat', 'search'] + (['images'] if image_ok else []), 'gui_enabled': False, 'unrelated_live_settings_preserved': True}))
