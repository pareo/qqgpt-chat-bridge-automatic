"""Check actual plugin load state, not just the Host HTTP listening port."""
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

import httpx
import tomlkit


def summarize_plugins(payload, required):
    if payload.get('success') is not True or not isinstance(payload.get('plugins'), list):
        raise ValueError('Invalid plugin status response')
    installed = {p['id']: p for p in payload['plugins']}
    states = {identifier: installed.get(identifier, {}).get('load_status', 'missing') for identifier in required}
    ready = all(states[identifier] == 'success' and installed[identifier].get('loaded') is True for identifier in required)
    return {'plugins_ready': ready, 'required_plugins': states}


def check_runtime():
    result = subprocess.run([sys.executable, '-m', 'src.cli.tool', 'host', 'open-webui', '-d', '/MaiMBot'], capture_output=True, text=True, check=True, timeout=4)
    url = urlsplit(json.loads(result.stdout)['url'])
    if url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.scheme not in ('http', 'https'):
        raise ValueError('Health check must use the local Host')
    ticket = parse_qs(url.fragment)['ticket'][0]
    required = []
    for identifier, directory in (('local.daifeilong', 'daifeilong'), ('maibot-team.snowluma-adapter', 'qq-connector')):
        settings = tomlkit.parse((Path('/MaiMBot/plugins') / directory / 'config.toml').read_text())
        if settings.get('plugin', {}).get('enabled', True):
            required.append(identifier)
    base = f'{url.scheme}://{url.netloc}'
    with httpx.Client(base_url=base, headers={'Origin': base, 'X-MaiBot-Host': '1'}, timeout=3, trust_env=False) as client:
        authenticated = False
        try:
            response = client.post('/api/host/session', json={'ticket': ticket})
            response.raise_for_status()
            authenticated = True
            response = client.get('/api/host/bots')
            response.raise_for_status()
            bot = next(b for b in response.json()['bots'] if b['directory'] == '/MaiMBot')
            if bot['status'] != 'running':
                raise RuntimeError('Bot process is not running')
            response = client.get('/api/host/bots/' + bot['bot_id'] + '/proxy/api/webui/plugins/installed')
            response.raise_for_status()
            return summarize_plugins(response.json(), required)
        finally:
            if authenticated:
                client.delete('/api/host/session').raise_for_status()


if __name__ == '__main__':
    try:
        state = check_runtime()
        print(json.dumps(state, ensure_ascii=False))
        sys.exit(0 if state['plugins_ready'] else 1)
    except httpx.HTTPStatusError as exc:
        print(f'Plugin runtime not ready: HTTP {exc.response.status_code} at {exc.request.url.path}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # Never log tickets, cookies, configuration or raw API response bodies.
        print('Plugin runtime not ready: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
