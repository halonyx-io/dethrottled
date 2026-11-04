"""Check deployment bundle integrity and Docker COPY sources in an actual wheel."""
import fnmatch
import hashlib
import io
import json
import shlex
import sys
import tarfile
import zipfile
from pathlib import Path

wheel = Path(sys.argv[1])
with zipfile.ZipFile(wheel) as package:
    metadata = json.loads(package.read('dethrottled/_stack/manifest.json'))
    content = package.read('dethrottled/_stack/context.tar.gz')
assert hashlib.sha256(content).hexdigest() == metadata['sha256']
with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
    names = set(archive.getnames())
    checked = 0
    for filename in sorted(n for n in names if n.endswith('Dockerfile')):
        text = archive.extractfile(filename).read().decode()
        # Browser-search uses its own directory as build context; other workers use root.
        prefix = 'browser-search/' if filename == 'browser-search/Dockerfile' else ''
        for line in text.replace('\\\n', ' ').splitlines():
            if not line.startswith('COPY ') or '--from=' in line:
                continue
            for source in shlex.split(line)[1:-1]:
                assert any(fnmatch.fnmatch(n, prefix + source.rstrip('/')) or
                           n.startswith(prefix + source.rstrip('/') + '/') for n in names), (
                               filename, source)
                checked += 1
    assert 'docker/searxng/settings.yml' in names and 'workers/runtime.py' in names
    api_recipe = archive.extractfile('Dockerfile').read().decode()
    root_sources = [s for line in api_recipe.splitlines() if line.startswith('COPY ')
                    for s in shlex.split(line)[1:-1]]
    assert 'Dockerfile' in root_sources, 'API nested wheel build needs its own Dockerfile'
print(json.dumps({'passed': True, 'version': metadata['version'],
                  'context_files': len(names), 'copy_sources_checked': checked,
                  'wheel_bytes': wheel.stat().st_size}))
