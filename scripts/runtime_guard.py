"""Recover corrupt, nonessential usage statistics before MaiBot starts."""
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time


def valid_usage(value):
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('usage_seconds'), dict):
        return False
    for plugin_id, seconds in value['usage_seconds'].items():
        if not isinstance(plugin_id, str) or not plugin_id.strip() or isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            return False
        try:
            if not math.isfinite(seconds) or seconds < 0:
                return False
        except OverflowError:
            return False
    return True


def repair_usage_file(path):
    """Never touch chat history/config; preserve damaged bytes for diagnosis."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        value = None
    if valid_usage(value):
        return None
    backup = path.with_name(path.name + '.corrupt-' + str(time.time_ns()))
    # Backup failures deliberately stop startup rather than losing evidence.
    path.rename(backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({'version': 1, 'usage_seconds': {}}, handle)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if not path.exists():
            backup.rename(path)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup


def main():
    backup = repair_usage_file(Path.cwd() / 'data/plugin_runtime/plugin_usage.json')
    if backup is not None:
        print('[启动保护] 插件使用时长记录损坏，已备份为 ' + backup.name + ' 并重置统计；聊天记录、配置和登录态不受影响。', flush=True)
    os.execvp('./docker-entrypoint.sh', ['./docker-entrypoint.sh', *sys.argv[1:]])


if __name__ == '__main__':
    main()
