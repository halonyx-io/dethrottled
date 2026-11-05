"""Include an inert, version-matched source context in wheels and sdists."""
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).parent
DIRECTORIES = ('src', 'requirements', 'browser-search', 'workers', 'format-worker',
               'media-worker', 'docling-worker', 'docker', 'adapters',
               'scripts', 'docs', 'evaluations')
FILES = ('Dockerfile', 'README.md', 'AGENTS.md', 'LICENSE', 'pyproject.toml', 'setup.py',
         'MANIFEST.in', '.dockerignore')


class BuildWithStack(build_py):
    def run(self):
        super().run()
        files = [ROOT / name for name in FILES]
        files += list(ROOT.glob('docker-compose*.yml'))
        for name in DIRECTORIES:
            files += [p for p in (ROOT / name).rglob('*') if p.is_file() and not p.is_symlink()
                      and not any(x in p.parts for x in ('__pycache__', '.pytest_cache', '_stack'))
                      and not p.name.endswith(('.pyc', '.pyo'))]
        missing = [str(p) for p in files[:len(FILES)] if not p.is_file()]
        if missing:
            raise RuntimeError('Incomplete deployment source context: ' + ', '.join(missing))
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as archive:
                for path in sorted(set(files)):
                    data = path.read_bytes()
                    info = tarfile.TarInfo(path.relative_to(ROOT).as_posix())
                    info.size = len(data)
                    info.mode = 0o755 if path.suffix == '.sh' else 0o644
                    archive.addfile(info, io.BytesIO(data))
        target = Path(self.build_lib) / 'dethrottled' / '_stack'
        target.mkdir(parents=True, exist_ok=True)
        content = buffer.getvalue()
        (target / 'context.tar.gz').write_bytes(content)
        version = self.distribution.get_version()
        (target / 'manifest.json').write_text(json.dumps({
            'version': version, 'sha256': hashlib.sha256(content).hexdigest(),
            'files': len(set(files))}, indent=2) + '\n')


setup(cmdclass={'build_py': BuildWithStack})
