"""Deploy .cloud-build/ to Vercel through the REST API.

The `vercel` CLI needs a token that can read the user and team. A token
scoped to just the project cannot, so deploy/vercel.sh falls back to this:
upload each file, then create the deployment.

    python deploy/vercel_api.py            production
    python deploy/vercel_api.py --preview  a preview deployment
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / '.cloud-build'
API = 'https://api.vercel.com'
SKIP = {'.vercel', 'node_modules', '__pycache__', '.DS_Store'}


def token() -> str:
    if os.getenv('VERCEL_TOKEN'):
        return os.environ['VERCEL_TOKEN']
    for line in (ROOT / '.env').read_text().splitlines():
        if line.startswith('VERCEL_TOKEN='):
            return line.split('=', 1)[1].strip()
    sys.exit('No VERCEL_TOKEN in the environment or .env')


def call(method: str, path: str, tok: str, body: bytes = None, headers: dict = None) -> dict:
    req = urllib.request.Request(API + path, data=body, method=method,
                                 headers={'Authorization': f'Bearer {tok}', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        sys.exit(f'{method} {path.split("?")[0]}: {e.code} {e.read().decode()[:400]}')


def main() -> None:
    tok = token()
    link = json.loads((BUILD / '.vercel/project.json').read_text())
    team = f"teamId={link['orgId']}"
    files = []
    for f in sorted(BUILD.rglob('*')):
        if f.is_file() and not SKIP & set(f.relative_to(BUILD).parts):
            data = f.read_bytes()
            files.append((f.relative_to(BUILD).as_posix(), hashlib.sha1(data).hexdigest(), data))
    body = {'name': link['projectName'], 'project': link['projectId'],
            'files': [{'file': name, 'sha': sha, 'size': len(data)} for name, sha, data in files]}
    if '--preview' not in sys.argv:
        body['target'] = 'production'
    req = urllib.request.Request(f'{API}/v13/deployments?{team}&skipAutoDetectionConfirmation=1',
                                 data=json.dumps(body).encode(), method='POST',
                                 headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            dep = json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b'{}').get('error', {})
        if err.get('code') != 'missing_files':
            sys.exit(f'create deployment: {e.code} {err}')
        missing = set(err['missing'])
        print(f'Uploading {len(missing)} of {len(files)} files…')
        for name, sha, data in files:
            if sha in missing:
                call('POST', f'/v2/files?{team}', tok, data,
                     {'Content-Type': 'application/octet-stream', 'x-vercel-digest': sha})
                missing.discard(sha)
        dep = call('POST', f'/v13/deployments?{team}&skipAutoDetectionConfirmation=1', tok,
                   json.dumps(body).encode(), {'Content-Type': 'application/json'})
    print(f"Building https://{dep['url']} …")
    while dep.get('readyState') not in ('READY', 'ERROR', 'CANCELED'):
        time.sleep(5)
        dep = call('GET', f"/v13/deployments/{dep['id']}?{team}", tok)
    print(dep['readyState'], f"https://{dep['url']}", ' '.join(dep.get('alias') or []))
    if dep['readyState'] != 'READY':
        sys.exit(dep.get('errorMessage') or 'deployment failed')


if __name__ == '__main__':
    main()
