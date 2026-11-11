"""Local, user-initiated Diving-Fish authorization and score import."""
import argparse
import asyncio
import os
from pathlib import Path
import re
import sys

import httpx

sys.path.insert(0, '/project/plugins')
from daifeilong import maimai


async def main(args):
    directory = Path(os.environ.get('DAIFEILONG_CONFIG_DIR', '/project/config/local'))
    proxy, client_id, client_secret = maimai.load_settings(directory)
    async with httpx.AsyncClient(proxy=proxy, timeout=40, follow_redirects=False) as client:
        if args.action == 'bind':
            scope = f'{maimai.READ} {maimai.WRITE}' if args.allow_import else maimai.READ
            link = await maimai.binding_link(client, args.qq, client_id, client_secret, scope)
            print('在浏览器打开下方链接，核对页面里的绑定 QQ 后同意。链接仅供本人使用。')
            print(link)
            return

        limit = 10 * 1024 * 1024
        source = sys.stdin.buffer.read(limit + 1)
        if len(source) > limit:
            raise maimai.MaimaiError('成绩页超过 10 MiB。')
        try:
            html = source.decode('utf-8-sig').strip()
        except UnicodeError as exc:
            raise maimai.MaimaiError('请把 NET 成绩页保存为 UTF-8 HTML。') from exc
        if not re.match(r'(?:<!doctype html\b[^>]*>\s*)?<html\b', html, re.I) or not re.search(r'</html>\s*$', html, re.I):
            raise maimai.MaimaiError('需要完整的 NET 成绩页 HTML 源代码。')
        token = await maimai.access_token(client, args.qq, client_id, client_secret, maimai.WRITE)
        result = await maimai.request(
            client, 'POST', maimai.BASE + '/player/update_records_html', importing=True,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'text/plain; charset=utf-8'},
            content=html.encode(),
        )
        if not isinstance(result, dict) or not all(type(result.get(k)) is int for k in ('updates', 'creates')):
            raise maimai.MaimaiError('水鱼未确认导入结果，请在网页核对成绩。')
        print(f'水鱼已接收成绩页，更新 {result["updates"]} 条、新增 {result["creates"]} 条。可以回群发 /B50。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('bind', 'import'))
    parser.add_argument('qq')
    parser.add_argument('--allow-import', action='store_true')
    try:
        asyncio.run(main(parser.parse_args()))
    except maimai.MaimaiError as exc:
        sys.exit(str(exc))
