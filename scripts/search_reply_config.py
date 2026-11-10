"""Update only search reply instructions; preserve private persona and routing."""
from pathlib import Path
import shutil
import sys
import time
import tomlkit

root = Path('/project')
sys.path.insert(0, str(root / 'plugins'))
from daifeilong.search_result import apply_reply_policy

path = root / 'config/generated/core/bot_config.toml'
bot = tomlkit.parse(path.read_text())
changed = apply_reply_policy(bot)
if changed:
    backup = root / 'config/generated/backups' / ('search-reply-' + str(time.time_ns()))
    backup.mkdir(parents=True)
    shutil.copyfile(path, backup / path.name)
    path.write_text(tomlkit.dumps(bot))
print(f'Search reply policy updated: {changed} group/private fields; persona and routing preserved.')
