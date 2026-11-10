"""Prepare isolated credentials and settings, without switching live AI routing."""
import json
from pathlib import Path
import secrets
import shutil
import time

root = Path('/project')
local = root / 'config/local'
generated = root / 'config/generated'
def read(name):
    return json.loads((local / name).read_text(encoding='utf-8-sig'))
def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
config, credentials = read('project.json'), read('secrets.json')
backup = generated / 'backups' / ('codex-prepare-' + str(time.time_ns()))
backup.mkdir(parents=True)
for name in ('project.json', 'secrets.json'):
    shutil.copyfile(local / name, backup / name)
if not credentials.get('agent_worker_token'):
    credentials['agent_worker_token'] = secrets.token_urlsafe(32)
config.setdefault('agent_worker', {'enabled': False, 'backend': 'codex-acp', 'url': 'http://codex-worker:18121', 'model': config['api']['chat_model'], 'reasoning_effort': 'medium', 'timeout_seconds': 240, 'queue_wait_seconds': 60})
config.setdefault('desktop_worker', {})['enabled'] = False
worker = config['agent_worker']
worker.setdefault('search_reasoning_effort', 'low')
worker.setdefault('search_max_rounds', 2)
if not worker.get('model'):
    worker['model'] = config['api']['chat_model']
if worker['backend'] != 'codex-acp' or worker['reasoning_effort'] not in ('low', 'medium', 'high'):
    raise ValueError('Invalid Codex backend configuration')
if worker['search_reasoning_effort'] not in ('low', 'medium', 'high') or type(worker['search_max_rounds']) is not int or not 1 <= worker['search_max_rounds'] <= 5:
    raise ValueError('Invalid search effort or search round budget')
write(local / 'project.json', config)
write(local / 'secrets.json', credentials)
write(generated / 'codex-worker.json', {'token': credentials['agent_worker_token'], 'model': worker['model'], 'reasoning_effort': worker['reasoning_effort'], 'search_reasoning_effort': worker['search_reasoning_effort'], 'search_max_rounds': worker['search_max_rounds'], 'timeout_seconds': worker['timeout_seconds']})
print('Isolated worker config prepared. GUI backend disabled; live agent routing unchanged.')
