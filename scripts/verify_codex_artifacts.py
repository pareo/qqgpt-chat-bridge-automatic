"""Download and validate probe outputs without generating again or sending QQ."""
import hashlib
import io
import json
from pathlib import Path
import httpx
from PIL import Image

folder = Path('/MaiMBot/data/verification')
evidence_path = folder / 'codex-probe.json'
evidence = json.loads(evidence_path.read_text())
credentials = json.loads(Path('/project/config/local/secrets.json').read_text(encoding='utf-8-sig'))
headers = {'Authorization': 'Bearer ' + credentials['agent_worker_token']}
with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
    for task in evidence:
        artifacts = task.get('artifacts', [])
        for index, artifact in enumerate(artifacts):
            response = client.get('http://codex-worker:18121/v1/tasks/' + task['id'] + '/artifacts/' + artifact['id'], headers=headers)
            response.raise_for_status()
            raw = response.content
            if len(raw) != artifact['bytes'] or len(raw) > 20*1024*1024 or hashlib.sha256(raw).hexdigest() != artifact['sha256']:
                raise ValueError('Artifact size or SHA-256 mismatch')
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
                image.verify()
            (folder / f'codex-{task["kind"]}-{index}.png').write_bytes(raw)
            print(json.dumps({'kind': task['kind'], 'bytes': len(raw), 'width': width, 'height': height, 'verified': True}))
        if artifacts:
            task['artifacts_verified'] = True
evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
