"""Look up reaction IDs in SnowLuma's face table and local additions."""
import ast
from functools import lru_cache
from pathlib import Path
import unicodedata


ALIASES = {
    '奶瓶': 148,
    '🍼': 148,
    '🍭': 147,
    '猴子': 128053,
    '猴脸': 128053,
}
EXTRA_SYSTEM_FACES = {143: '帅'}
EXTRA_UNICODE_FACES = {'㊗': '祝'}


@lru_cache(maxsize=1)
def face_table():
    plugin_dir = Path(__file__).resolve().parent
    candidates = (
        plugin_dir.parent / 'qq-connector' / 'qq_face_map.py',
        plugin_dir.parents[1] / 'vendor' / 'qq-connector' / 'qq_face_map.py',
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise FileNotFoundError('找不到 SnowLuma 表情表')

    # Read the mapping without importing the other plugin into this runner.
    tables = {}
    for node in ast.parse(source.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in ('QQ_FACE_DESCRIPTIONS', '_UNICODE_FACE_DESCRIPTIONS'):
                tables[node.target.id] = ast.literal_eval(node.value)
    system = {int(key): name for key, name in tables['QQ_FACE_DESCRIPTIONS'].items()}
    system.update(EXTRA_SYSTEM_FACES)
    unicode_faces = {
        ord(symbol): name
        for symbol, name in {**tables['_UNICODE_FACE_DESCRIPTIONS'], **EXTRA_UNICODE_FACES}.items()
    }
    return system, unicode_faces


def lookup_faces(names):
    system, unicode_faces = face_table()
    by_id = {**unicode_faces, **system}
    # Prefer QQ system faces for shared names and use the lower ID for variants.
    by_name = {}
    for emoji_id, name in sorted(by_id.items()):
        by_name.setdefault(name, emoji_id)
    by_name.update(ALIASES)

    matched, unknown = [], []
    seen = set()
    for original in names:
        name = unicodedata.normalize('NFKC', original).replace('\ufe0f', '').strip().strip('[]【】/').strip()
        emoji_id = by_name.get(name)
        if emoji_id is None and len(name) == 1 and ord(name) in unicode_faces:
            emoji_id = ord(name)
        if emoji_id is None and name.isascii() and name.isdecimal() and len(name) <= 7:
            emoji_id = int(name)
        if not emoji_id or emoji_id not in by_id:
            unknown.append(original)
        elif emoji_id not in seen:
            matched.append({'query': original, 'name': by_id[emoji_id], 'emoji_id': emoji_id})
            seen.add(emoji_id)
    return matched, unknown
