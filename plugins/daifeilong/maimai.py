"""Diving-Fish catalog and user-authorized maimai DX scores."""
from __future__ import annotations

import asyncio
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlsplit

import httpx


BASE = 'https://www.diving-fish.com/api/maimaidxprober'
AUTH = 'https://auth.diving-fish.com'
ALIASES = 'https://www.yuzuchan.moe/api/maimaidx/maimaidxalias'
SYNC = 'https://maimai.diving-fish.com/manual/docs/update-records/proxy/'
READ = 'prober.records.read'
WRITE = 'prober.records.write'
BIND_HELP = '请在运行大肥龙的电脑执行 scripts/maimai.ps1 的 bind 操作，按水鱼页面完成一次授权。'
LEVELS = ('绿', '黄', '红', '紫', '白')
DIFFICULTY_NAMES = ('basic', 'advanced', 'expert', 'master', 're:master')
CHART_TYPES = {'SD': '标准', 'DX': 'DX', 'UTAGE': '宴会场'}


class MaimaiError(RuntimeError):
    pass


def load_settings(directory: Path):
    try:
        config = json.loads((directory / 'project.json').read_text(encoding='utf-8-sig'))
        secrets = json.loads((directory / 'secrets.json').read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise MaimaiError('舞萌的本地配置无法读取。') from exc
    return (str(config.get('maimai', {}).get('proxy', '')).strip() or None,
            str(secrets.get('diving_fish_client_id', '')).strip(),
            str(secrets.get('diving_fish_client_secret', '')).strip())


async def request(client, method, url, *, importing=False, **kwargs):
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        message = '导入结果未确认，请先到水鱼检查成绩。' if importing else '暂时连不上舞萌数据服务，稍后再查。'
        raise MaimaiError(message) from exc
    if importing and response.status_code >= 500:
        raise MaimaiError('导入结果未确认，请先到水鱼检查成绩。')
    try:
        payload = response.json()
    except ValueError as exc:
        raise MaimaiError(f'舞萌数据服务返回了无法读取的结果（HTTP {response.status_code}）。') from exc
    if not response.is_success:
        error = payload.get('error') if isinstance(payload, dict) else None
        if error == 'consent_required':
            raise MaimaiError('水鱼尚未授权该操作。' + BIND_HELP)
        if response.status_code == 429:
            raise MaimaiError('舞萌数据服务限制了请求频率，稍后再试。')
        if response.status_code in (401, 403):
            raise MaimaiError('水鱼未授权该操作，请检查应用配置、绑定和权限。')
        raise MaimaiError(f'舞萌数据服务拒绝了请求（HTTP {response.status_code}）。')
    return payload


def subject_ref(qq, client_id, client_secret):
    if not re.fullmatch(r'[1-9]\d{4,11}', qq, flags=re.ASCII):
        raise MaimaiError('这条消息没有可用的 QQ 账号。')
    if not client_id or not client_secret:
        raise MaimaiError('管理员需要先配置水鱼 OAuth 应用的 Client ID 和 Client Secret。')
    return sha256(f'{client_id}:{qq}'.encode()).hexdigest()


def official_auth_url(url):
    try:
        parts = urlsplit(url)
        if parts.scheme == 'https' and parts.netloc == 'auth.diving-fish.com':
            return url
    except ValueError:
        pass
    raise MaimaiError('水鱼返回的授权地址无法验证。')


async def oauth_request(client, key, data):
    metadata = await request(client, 'GET', AUTH + '/.well-known/openid-configuration')
    endpoint = official_auth_url(metadata.get(key, '') if isinstance(metadata, dict) else '')
    result = await request(client, 'POST', endpoint, data=data)
    if not isinstance(result, dict):
        raise MaimaiError('水鱼授权服务返回的结果无法读取。')
    return result


async def binding_link(client, qq, client_id, client_secret, scope):
    ref = subject_ref(qq, client_id, client_secret)
    response = await oauth_request(client, 'device_authorization_endpoint', {
        'client_id': client_id, 'client_secret': client_secret, 'scope': scope,
        'subject_ref': ref, 'binding_label': f'QQ {qq[:2]}****{qq[-2:]}',
    })
    return official_auth_url(response.get('verification_uri_complete', ''))


async def access_token(client, qq, client_id, client_secret, scope):
    ref = subject_ref(qq, client_id, client_secret)
    result = await oauth_request(client, 'token_endpoint', {
        'grant_type': 'urn:diving-fish:params:oauth:grant-type:on-behalf-of',
        'client_id': client_id, 'client_secret': client_secret, 'subject': 'ref:' + ref, 'scope': scope,
    })
    token = result.get('access_token')
    if not isinstance(token, str) or not token:
        raise MaimaiError('水鱼没有签发该操作的授权令牌。')
    return token


async def query_b50(client, token):
    result = await request(client, 'POST', BASE + '/query/player',
                           headers={'Authorization': 'Bearer ' + token}, json={'b50': True})
    charts = result.get('charts') if isinstance(result, dict) else None
    if not isinstance(charts, dict) or not all(isinstance(charts.get(k), list) for k in ('sd', 'dx')):
        raise MaimaiError('水鱼返回的 B50 格式无法读取。')
    if not charts['sd'] and not charts['dx']:
        raise MaimaiError(f'这个账号暂时没有已同步成绩。同步教程 {SYNC}')
    return result


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', str(text)).casefold().split())


class SongCatalog:
    def __init__(self):
        self.entries = []
        self.fetched_at = 0.0
        self.aliases_by_id = {}
        self.lock = asyncio.Lock()

    async def get(self, client):
        async with self.lock:
            if self.entries and time.monotonic() - self.fetched_at < 1800:
                return self.entries
            try:
                songs, aliases = await asyncio.gather(
                    request(client, 'GET', BASE + '/music_data'), request(client, 'GET', ALIASES),
                    return_exceptions=True,
                )
                if isinstance(songs, Exception):
                    raise songs
                if not isinstance(songs, list) or not songs:
                    raise MaimaiError('水鱼返回的曲库格式暂时无法读取。')
                if isinstance(aliases, dict) and isinstance(aliases.get('content'), list):
                    self.aliases_by_id = {}
                    for item in aliases['content']:
                        key = str(item.get('SongID', ''))
                        if key.isascii() and key.isdecimal() and isinstance(item.get('Alias'), list):
                            self.aliases_by_id.setdefault(int(key) % 10000, set()).update(normalize(a) for a in item['Alias'])
                entries = [(song, {normalize(song['title']), *self.aliases_by_id.get(int(song['id']) % 10000, ())})
                           for song in songs if str(song.get('id', '')).isdigit()]
            except MaimaiError:
                if self.entries:
                    return self.entries
                raise
            self.entries = entries
            self.fetched_at = time.monotonic()
            return self.entries

    async def describe(self, client, query):
        full_term, separator, level = normalize(query).partition('|')
        term = full_term.strip()
        level = level.strip()
        if not separator:
            title, space, suffix = term.rpartition(' ')
            if space and (suffix in LEVELS or suffix in DIFFICULTY_NAMES
                          or re.fullmatch(r'[0-9]{1,2}(?:\+|\.[0-9]+)?', suffix)):
                term, level = title, suffix
        if not term or len(term) > 100:
            raise MaimaiError('用法 /查歌 曲名、别名或数字 ID。可用空格追加难度，例如 /查歌 水神2 紫。')
        entries = await self.get(client)
        matches = []
        if not separator and level and len(full_term) <= 100:
            matches = [song for song, names in entries if full_term in names]
            if matches:
                level = ''
        if not matches and term.isascii() and term.isdecimal():
            matches = [song for song, _ in entries if str(song['id']) == term]
        elif not matches:
            matches = [song for song, names in entries if term in names]
        if not matches:
            matches = [song for song, names in entries if any(term in name for name in names)]
        if not matches:
            return '没找到这首歌，换个别名、全名或曲目 ID 试试。'
        if len({normalize(s['title']) for s in matches}) > 1 or len(matches) > 3:
            options = '\n'.join(f"{s['id']} · {s['title']} ({s['type']})" for s in matches[:6])
            return f'找到 {len(matches)} 首，请用曲目 ID 再查一次。\n{options}'
        chart_lines = []
        for song in matches:
            kind = CHART_TYPES.get(song['type'], song['type'])
            for index, (grade, constant) in enumerate(zip(song['level'], song['ds'])):
                color = LEVELS[index] if index < len(LEVELS) and int(song['id']) < 100000 else ''
                name = DIFFICULTY_NAMES[index] if color else ''
                if level and level not in {color, normalize(grade), name, normalize(constant)}:
                    continue
                chart_lines.append(f'{kind} {color}{grade}（定数 {constant}）')
        song = matches[0]
        info = song.get('basic_info', {})
        ids = ' / '.join(str(s['id']) for s in matches)
        header = f"{song['title']} · ID {ids}\n{info.get('artist', '')} · BPM {info.get('bpm', '—')}"
        return header + '\n' + ('\n'.join(chart_lines) if chart_lines else '没有匹配该难度的谱面。')


def bests_html(result):
    def section(label, key, limit, style):
        cards = []
        scores = result['charts'][key][:limit]
        for rank, score in enumerate(scores, 1):
            title = escape(str(score.get('title') or score.get('song_id') or '未知曲目'))
            grade = escape(str(score.get('level') or '—'))
            kind = CHART_TYPES.get(score.get('type'), '—')
            index = score.get('level_index')
            color = LEVELS[index] if isinstance(index, int) and 0 <= index < len(LEVELS) else ''
            achievement = float(score['achievements'])
            rating = int(score['ra'])
            cards.append(
                f'<article><div class="meta">#{rank:02d} <span>{kind} {color}{grade}</span></div>'
                f'<b>{title}</b><div class="stats">{achievement:.4f}% <span>＋{rating}</span></div></article>'
            )
        heading = f'{label} · {sum(int(score["ra"]) for score in scores)} Rating'
        return f'<section class="{style}"><h2>{heading}</h2><div class="cards">' + ''.join(cards) + '</div></section>'

    name = escape(str(result.get('nickname') or '舞萌玩家'))
    rating = int(result['rating'])
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>
    *{{box-sizing:border-box}} body{{margin:0;padding:30px;background:#0e1322;color:#e7edf7;
    font:18px system-ui,"Noto Sans CJK SC",sans-serif}} header{{display:flex;justify-content:space-between;
    align-items:center;gap:24px;border-bottom:1px solid #344053;padding-bottom:20px}}
    h1{{margin:0;font-size:36px}} .name{{color:#a4b3cc;overflow-wrap:anywhere;margin-top:8px}}
    .rating{{background:#253652;color:#c2f7ef;border-radius:12px;padding:14px 20px;font-size:26px;
    font-weight:700;white-space:nowrap}} h2{{font-size:20px;margin:24px 0 12px}}
    .new h2,.new .stats span{{color:#87f2d7}} .old h2,.old .stats span{{color:#bcb7ff}}
    .cards{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}}
    article{{background:#1c263b;border-radius:10px;padding:10px;min-width:0}}
    .meta,.stats{{display:flex;justify-content:space-between;gap:6px;white-space:nowrap}}
    .meta{{color:#a4b3cc;font-size:13px}} b{{display:block;margin:6px 0;white-space:nowrap;overflow:hidden;
    text-overflow:ellipsis;font-size:17px}} .stats{{font-size:16px;font-variant-numeric:tabular-nums}}
    footer{{color:#a4b3cc;margin-top:16px;font-size:14px}}
    </style><header><div><h1>舞萌 DX · Best 50</h1><div class="name">{name}</div></div>
    <div class="rating">{rating} Rating</div></header>
    {section('现版本 B15', 'dx', 15, 'new')}{section('旧版本 B35', 'sd', 35, 'old')}
    <footer>数据来源 · 水鱼查分器</footer></html>"""
