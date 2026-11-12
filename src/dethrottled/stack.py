"""Explicit Docker Compose lifecycle for a packaged, private managed stack."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

LABEL = 'io.dethrottled.managed'
PROFILES = {'default': [], 'media': ['media'], 'layout': ['layout'], 'full': ['full']}
BASE = ['dethrottled', 'dnb', 'searxng', 'format-worker']


class StackError(RuntimeError):
    pass


def run(args, *, capture=True, env=None, cwd=None):
    result = subprocess.run(args, text=True, capture_output=capture, env=env, cwd=cwd,
                            **({} if capture else {'stdout': sys.stderr}))
    if result.returncode:
        raise StackError((result.stderr or 'Command failed: ' + ' '.join(args))[-2000:])
    return result.stdout if capture else ''


def prerequisites():
    if not shutil.which('docker'):
        raise StackError('Docker Engine and the Compose plugin are required. Install them using '
                         'https://docs.docker.com/engine/install/ then retry. '
                         'No system packages or privileges were changed.')
    engine = json.loads(run(['docker', 'info', '--format', '{{json .}}']))
    if engine.get('OSType') != 'linux':
        raise StackError('The managed workers require Linux containers. Switch Docker Desktop '
                         'to its Linux engine, or use a Linux Docker host.')
    if engine.get('Architecture') not in {'x86_64', 'amd64', 'aarch64', 'arm64'}:
        raise StackError('Managed worker images are validated for native AMD64 and ARM64; '
                         'this Docker host reports ' + str(engine.get('Architecture')) + '.')
    compose = run(['docker', 'compose', 'version'])
    version = re.search(r'v?(\d+)\.\d+', compose)
    if not version or int(version[1]) < 2:
        raise StackError('Docker Compose plugin v2 or newer is required.')
    return {k: engine.get(k) for k in ('ServerVersion', 'Architecture', 'NCPU', 'MemTotal',
                                       'DockerRootDir', 'OperatingSystem')}


def clean_environment(port):
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ('DETHROTTLED_', 'COMPOSE_', 'CRAWL4AI_'))}
    for switch in ('DETHROTTLED_ADBLOCK', 'DETHROTTLED_RERANK', 'DETHROTTLED_RERANK_DEPTH',
                   'DETHROTTLED_RERANK_MAX_TOKENS', 'DETHROTTLED_RERANK_TEXT_CHARS',
                   'DETHROTTLED_RERANK_THREADS', 'DETHROTTLED_RERANK_KEEP_FIRST'):
        if switch in os.environ:
            env[switch] = os.environ[switch]
    env.update(DETHROTTLED_PORT=str(port), DETHROTTLED_BIND='127.0.0.1',
               DETHROTTLED_VERSION=__version__)
    return env


def check_port(port):
    with socket.socket() as sock:
        # POSIX listeners can restart while closed connections remain in TIME_WAIT.
        # REUSEADDR still refuses an active listener; Windows semantics differ.
        if os.name != 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise StackError(f'Port {port} is in use; choose --port.') from exc


def stack_root(project):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,55}', project):
        raise StackError('Project must be 1-56 lowercase letters, digits, underscores or hyphens.')
    base = os.getenv('DETHROTTLED_STACK_HOME')
    if not base:
        base = (Path(os.getenv('LOCALAPPDATA', Path.home() / 'AppData/Local')) if os.name == 'nt'
                else Path(os.getenv('XDG_DATA_HOME', Path.home() / '.local/share')))
        base = Path(base) / 'dethrottled' / 'stacks'
    return Path(base).expanduser().resolve() / project


def prepare_context(root):
    resource = Path(__file__).parent / '_stack'
    try:
        manifest = json.loads((resource / 'manifest.json').read_text())
        content = (resource / 'context.tar.gz').read_bytes()
    except (OSError, ValueError) as exc:
        raise StackError('Packaged deployment context is missing. Install a built wheel or sdist; '
                         'editable source users should use the repository Compose files.') from exc
    if (manifest['version'] != __version__
            or hashlib.sha256(content).hexdigest() != manifest['sha256']):
        raise StackError('Deployment bundle integrity/version mismatch; reinstall the package.')
    target = root / __version__
    if target.exists():
        if not (target / 'bundle.sha256').exists() or (
                target / 'bundle.sha256').read_text() != manifest['sha256']:
            raise StackError('Existing deployment directory has a different bundle; preserve it '
                             'and choose another project or remove that directory deliberately.')
        return target
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.context-', dir=root) as temporary:
        stage = Path(temporary)
        import io
        with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
            members = archive.getmembers()
            for item in members:
                path = Path(item.name)
                if (path.is_absolute() or '..' in path.parts or not item.isfile()
                        or item.name.startswith(('/', '\\')) or '\\' in item.name
                        or re.match(r'^[A-Za-z]:', item.name)):
                    raise StackError('Unsafe path or non-file in deployment bundle.')
            for item in members:
                dest = stage / item.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as source:
                    dest.write_bytes(source.read())
                dest.chmod(item.mode & 0o777)
        (stage / 'bundle.sha256').write_text(manifest['sha256'])
        stage.rename(target)
    return target


def containers(project, *, managed=True):
    ids = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project])
    if not ids.strip():
        return []
    values = json.loads(run(['docker', 'inspect', *ids.split()]))
    if managed and any(c.get('Config', {}).get('Labels', {}).get(LABEL) != '1' for c in values):
        raise StackError('Project is unmanaged. Choose a different --project.')
    return values


def command(context, project):
    return ['docker', 'compose', '--env-file', os.devnull, '--project-name', project,
            '-f', str(context / 'docker-compose.yml'), '-f', str(context / 'managed.json')]


def inspect_status(project, port, profile):
    active = containers(project)
    services = {}
    for c in active:
        name = c['Config']['Labels']['com.docker.compose.service']
        state = c['State']
        health = state.get('Health', {}).get('Status')
        readiness = 'unavailable'
        if state['Running']:
            readiness = {None: 'running', 'healthy': 'ready',
                         'starting': 'initializing'}.get(health, 'unavailable')
        services[name] = {'state': readiness, 'container_state': state['Status'],
                          'health': health}
    expected = BASE + (['media-worker'] if profile in {'media', 'full'} else []) + (
        ['docling-worker'] if profile in {'layout', 'full'} else [])
    for name in expected:
        services.setdefault(name, {'state': 'unavailable', 'container_state': 'missing'})
    api = next((c for c in active if c['Config']['Labels'][
        'com.docker.compose.service'] == 'dethrottled' and c['State']['Running']), None)
    if api:
        try:
            probe = ('import json,urllib.request;from dethrottled import workers;'
                     'r=workers.status();'
                     '\ntry: urllib.request.urlopen("http://searxng:8080/config",timeout=2);'
                     'r["searxng"]={"status":"ready"}'
                     '\nexcept Exception:r["searxng"]={"status":"unavailable"}'
                     '\nprint(json.dumps(r))')
            workers = json.loads(run(['docker', 'exec', api['Id'], 'python', '-c', probe]))
            names = {'browser': 'dnb', 'renderer': 'dnb',
                     'formats': 'format-worker', 'speech': 'media-worker',
                     'layout': 'docling-worker', 'searxng': 'searxng'}
            for worker, report in workers.items():
                name = names[worker]
                if name not in services:
                    continue
                state = report['status']
                services[name].update(state='ready' if state == 'ready' else 'initializing'
                                      if report.get('initialization') == 'first_use_download'
                                      else 'unavailable', probe=report)
            if 'dnb' in services:
                probes = {k: workers.get(k, {}) for k in ('browser', 'renderer')}
                services['dnb'].update(
                    state='ready' if all(r.get('status') == 'ready' for r in probes.values())
                    else 'unavailable', probe=probes)
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as response:
                health = json.load(response)
            services['dethrottled']['runtime_version'] = health.get('version')
            services['dethrottled']['state'] = ('ready' if health.get('version') == __version__
                                                else 'unavailable')
        except (StackError, OSError, ValueError, urllib.error.URLError) as exc:
            services['dethrottled'].update(state='unavailable', reason=str(exc)[:250])
    return {'project': project, 'package_version': __version__, 'profile': profile,
            'endpoint': f'http://127.0.0.1:{port}', 'services': services,
            'ready': all(services[n]['state'] == 'ready' for n in expected),
            'volumes_preserved_on_down': True, 'selected_services': expected}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='dethrottled stack', description=__doc__)
    parser.add_argument('action', choices=['up', 'status', 'down', 'configure'])
    parser.add_argument('--project')
    parser.add_argument('--port', type=int)
    parser.add_argument('--profile', choices=list(PROFILES))
    parser.add_argument('--timeout', type=int, default=180,
                        help='Readiness wait after build, seconds')
    parser.add_argument('--json', action='store_true', help='Machine-readable final report')
    parser.add_argument('--output', type=Path, help='Save a Guided Setup override here')
    parser.add_argument('--config', type=Path, help='Apply a saved Guided Setup override')
    args = parser.parse_args(argv)
    try:
        from . import guided

        if args.config and args.action != 'up':
            raise StackError('--config is supported by stack up.')
        if args.output and args.action != 'configure':
            raise StackError('--output is supported by stack configure.')
        plan = guided.load(args.config) if args.config else None
        if plan:
            metadata = plan[guided.PLAN_KEY]
            if any(value is not None and value != metadata[name]
                   for name, value in (('project', args.project), ('port', args.port),
                                       ('profile', args.profile))):
                raise StackError('Project, port and profile must match the Guided Setup override.')
            args.project, args.port, args.profile = (
                metadata['project'], metadata['port'], metadata['profile'])
        args.project = args.project or 'dethrottled-managed'
        if args.port is not None and not 1 <= args.port <= 65535:
            raise StackError('Port must be between 1 and 65535.')
        if args.timeout < 1:
            raise StackError('Timeout must be positive.')
        engine = prerequisites()
        root = stack_root(args.project)
        settings = root / 'project.json'
        previous = json.loads(settings.read_text()) if settings.exists() else {}
        if args.action == 'configure':
            if args.json:
                raise StackError('Guided Setup requires interactive choices.')
            return guided.run_guided(args, engine, previous,
                                     containers(args.project, managed=False), run, check_port)
        plan = plan or previous.get('guided')
        port = args.port or previous.get('port', 8787)
        profile = args.profile or previous.get('profile', 'default')
        existing = containers(args.project)
        if args.action == 'up':
            port_is_ours = any(
                c['State']['Running']
                and c['Config']['Labels'].get('com.docker.compose.service') == 'dethrottled'
                and any(binding.get('HostPort') == str(port)
                        and binding.get('HostIp') in {'127.0.0.1', '0.0.0.0', ''}
                        for binding in (c.get('NetworkSettings', {}).get('Ports', {})
                                        .get('8787/tcp') or []))
                for c in existing
            )
            if not port_is_ours:
                check_port(port)
            context = prepare_context(root)
            # Managed image names never overwrite the production :local tags.
            build_services = ['dethrottled', 'dnb', 'format-worker',
                              'media-worker', 'docling-worker']
            override = {'services': {n: {'labels': {LABEL: '1',
                         'io.dethrottled.version': __version__},
                         **({'image': f'dethrottled-managed-{n}:{__version__}'}
                            if n in build_services else {})}
                         for n in [*BASE, 'media-worker', 'docling-worker']}}
            if plan:
                for name, options in plan['services'].items():
                    override['services'][name].update(options)
            (context / 'managed.json').write_text(json.dumps(override, indent=2))
            settings.write_text(json.dumps({'port': port, 'profile': profile,
                                           'version': __version__,
                                           **({'guided': plan} if plan else {})}, indent=2))
            if engine:
                print(f'Docker host: {engine["Architecture"]}, {engine["NCPU"]} CPUs, '
                      f'{engine["MemTotal"] / 1024**3:.1f} GiB RAM. Selected profile: {profile}. '
                      'Model downloads require network access and disk space; see '
                      'https://github.com/halonyx-io/dethrottled/blob/main/docs/REQUIREMENTS.md '
                      'for measured costs.', file=sys.stderr)
            print('Preparing selected worker images (first build downloads dependencies/models). '
                  'Optional speech/layout models initialize on first use.', file=sys.stderr)
            started = time.monotonic()
            cmd = command(context, args.project)
            for selected in PROFILES[profile]:
                cmd += ['--profile', selected]
            try:
                run([*cmd, 'up', '-d', '--build'], capture=False,
                    env=clean_environment(port), cwd=context)
            except StackError as exc:
                report = inspect_status(args.project, port, profile)
                report.update(started=False, error=str(exc),
                              startup_seconds=round(time.monotonic() - started, 2))
                print(json.dumps(report, indent=2))
                return 1
            deadline = time.monotonic() + args.timeout
            while True:
                report = inspect_status(args.project, port, profile)
                accepted = all(s['state'] == 'ready' or (
                    n in {'media-worker', 'docling-worker'} and s['state'] == 'initializing'
                    and s.get('probe', {}).get('initialization') == 'first_use_download')
                    for n, s in report['services'].items() if n in report['selected_services'])
                if accepted or time.monotonic() >= deadline:
                    break
                time.sleep(2)
            if accepted:
                legacy = [c['Id'] for c in existing if c['State']['Running'] and
                          c['Config']['Labels']['com.docker.compose.service'] in
                          {'browser-search', 'crawl4ai'}]
                if legacy:
                    run(['docker', 'stop', *legacy])
            report['startup_seconds'] = round(time.monotonic() - started, 2)
            report['started'] = accepted
            print(json.dumps(report, indent=2))
            if not accepted:
                return 1
        elif args.action == 'status':
            print(json.dumps(inspect_status(args.project, port, profile), indent=2))
        else:
            if not existing:
                print(json.dumps({'project': args.project, 'state': 'stopped',
                                  'volumes_preserved': True}))
                return 0
            context = root / previous.get('version', __version__)
            if not (context / 'managed.json').exists():
                raise StackError('Managed project metadata is missing; refusing to guess.')
            run([*command(context, args.project), '--profile', '*', 'down'], capture=False,
                env=clean_environment(port), cwd=context)
            print(json.dumps({'project': args.project, 'state': 'stopped',
                              'volumes_preserved': True}))
        return 0
    except (KeyboardInterrupt, EOFError):
        print('Guided Setup cancelled.', file=sys.stderr)
        return 1
    except (StackError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc), 'action': args.action}), file=sys.stderr)
        return 1
