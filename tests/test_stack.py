"""Lifecycle safety and archive validation without Docker or network access."""
import hashlib
import io
import json
import tarfile

import pytest

from dethrottled import stack


def test_project_cannot_escape_state_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('DETHROTTLED_STACK_HOME', str(tmp_path))
    assert stack.stack_root('test-project') == tmp_path / 'test-project'
    for value in ('../production', '/tmp/x', 'UPPERCASE', '', 'a' * 57):
        with pytest.raises(stack.StackError):
            stack.stack_root(value)


def test_parent_compose_environment_and_secrets_are_not_inherited(monkeypatch):
    monkeypatch.setenv('COMPOSE_FILE', '/private/production.yml')
    monkeypatch.setenv('DETHROTTLED_EXA_API_KEY', 'private-secret')
    monkeypatch.setenv('DETHROTTLED_ADBLOCK', '0')
    env = stack.clean_environment(19087)
    assert 'COMPOSE_FILE' not in env and 'DETHROTTLED_EXA_API_KEY' not in env
    assert env['DETHROTTLED_BIND'] == '127.0.0.1'
    assert env['DETHROTTLED_PORT'] == '19087'
    assert env['DETHROTTLED_ADBLOCK'] == '0'


def test_unmanaged_project_is_never_adopted(monkeypatch):
    replies = iter(['container-id', json.dumps([{'Config': {'Labels': {}}}])])
    monkeypatch.setattr(stack, 'run', lambda *a, **k: next(replies))
    with pytest.raises(stack.StackError, match='unmanaged'):
        stack.containers('production')


def test_down_preserves_data_and_uses_saved_version(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('DETHROTTLED_STACK_HOME', str(tmp_path))
    root = tmp_path / 'test'
    context = root / 'older-version'
    context.mkdir(parents=True)
    (root / 'project.json').write_text(json.dumps({
        'version': 'older-version', 'port': 19087, 'profile': 'full'}))
    (context / 'managed.json').write_text('{}')
    monkeypatch.setattr(stack, 'prerequisites', lambda: None)
    monkeypatch.setattr(stack, 'containers', lambda p: [{'managed': True}])
    calls = []
    monkeypatch.setattr(stack, 'run', lambda cmd, **kw: calls.append(cmd))
    assert stack.main(['down', '--project', 'test']) == 0
    assert calls[0][-3:] == ['--profile', '*', 'down']
    assert '--volumes' not in calls[0] and '-v' not in calls[0]
    assert str(context / 'docker-compose.yml') in calls[0]
    assert json.loads(capsys.readouterr().out)['volumes_preserved'] is True


def test_archive_traversal_is_rejected(monkeypatch, tmp_path):
    resource = tmp_path / '_stack'
    resource.mkdir()
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        member = tarfile.TarInfo('../outside')
        member.size = 1
        archive.addfile(member, io.BytesIO(b'x'))
    content = data.getvalue()
    (resource / 'context.tar.gz').write_bytes(content)
    (resource / 'manifest.json').write_text(json.dumps({
        'version': stack.__version__, 'sha256': hashlib.sha256(content).hexdigest()}))
    monkeypatch.setattr(stack, '__file__', str(tmp_path / 'stack.py'))
    with pytest.raises(stack.StackError, match='Unsafe'):
        stack.prepare_context(tmp_path / 'project')
    assert not (tmp_path / 'outside').exists()


def test_missing_docker_is_actionable_and_does_not_install(monkeypatch, capsys):
    monkeypatch.setattr(stack.shutil, 'which', lambda name: None)
    assert stack.main(['up']) == 1
    error = json.loads(capsys.readouterr().err)
    assert 'Docker Engine' in error['error'] and 'No system packages' in error['error']


def test_partial_start_failure_reports_workers(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('DETHROTTLED_STACK_HOME', str(tmp_path))
    monkeypatch.setattr(stack, 'prerequisites', lambda: None)
    monkeypatch.setattr(stack, 'containers', lambda p: [])
    context = tmp_path / 'test' / stack.__version__
    context.mkdir(parents=True)
    monkeypatch.setattr(stack, 'prepare_context', lambda root: context)
    monkeypatch.setattr(stack, 'inspect_status', lambda *a: {
        'ready': False, 'services': {'browser-search': {'state': 'unavailable'}}})

    def fail(*args, **kwargs):
        raise stack.StackError('worker image build failed')

    monkeypatch.setattr(stack, 'run', fail)
    assert stack.main(['up', '--project', 'test', '--port', '19089']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['started'] is False
    assert result['services']['browser-search']['state'] == 'unavailable'
    assert 'image build failed' in result['error']


def test_wrong_container_platform_is_explained_before_build(monkeypatch):
    monkeypatch.setattr(stack.shutil, 'which', lambda name: '/usr/bin/docker')
    monkeypatch.setattr(stack, 'run', lambda *a, **k: json.dumps({'OSType': 'windows'}))
    with pytest.raises(stack.StackError, match='Linux containers'):
        stack.prerequisites()


def test_unsupported_native_architecture_is_explained(monkeypatch):
    monkeypatch.setattr(stack.shutil, 'which', lambda name: '/usr/bin/docker')
    monkeypatch.setattr(stack, 'run', lambda *a, **k: json.dumps({
        'OSType': 'linux', 'Architecture': 'armv7l'}))
    with pytest.raises(stack.StackError, match='AMD64 and ARM64'):
        stack.prerequisites()


def test_port_probe_rejects_live_listener():
    import socket
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        with pytest.raises(stack.StackError, match='in use'):
            stack.check_port(listener.getsockname()[1])


@pytest.mark.skipif(stack.os.name == 'nt', reason='POSIX TIME_WAIT restart semantics')
def test_port_probe_allows_restart_after_closed_connections():
    import socket
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.listen()
        with socket.create_connection(('127.0.0.1', port)) as client:
            accepted, _ = listener.accept()
            accepted.close()
            assert client.recv(1) == b''
    stack.check_port(port)


def test_status_ignores_stale_healthy_flag_on_stopped_container(monkeypatch):
    monkeypatch.setattr(stack, 'containers', lambda _: [{
        'Config': {'Labels': {'com.docker.compose.service': 'dnb'}},
        'State': {'Running': False, 'Status': 'exited', 'Health': {'Status': 'healthy'}},
    }])
    status = stack.inspect_status('test', 19087, 'default')
    assert status['services']['dnb']['state'] == 'unavailable'


def test_up_checks_port_when_only_other_services_exist(monkeypatch, tmp_path):
    monkeypatch.setenv('DETHROTTLED_STACK_HOME', str(tmp_path))
    root = tmp_path / 'test'
    root.mkdir()
    (root / 'project.json').write_text('{"port":19087}')
    monkeypatch.setattr(stack, 'prerequisites', lambda: None)
    monkeypatch.setattr(stack, 'containers', lambda _: [{
        'Config': {'Labels': {'com.docker.compose.service': 'format-worker'}},
        'State': {'Running': True},
    }])

    def busy(port):
        assert port == 19087
        raise stack.StackError('port in use')

    monkeypatch.setattr(stack, 'check_port', busy)
    monkeypatch.setattr(stack, 'prepare_context',
                        lambda _: pytest.fail('occupied port reached setup'))
    assert stack.main(['up', '--project', 'test']) == 1


def test_guided_setup_saves_portable_plan_without_starting(tmp_path, monkeypatch, capsys):
    from dethrottled import guided

    disk = 145 * guided.GIB
    edge = {"cpus": 8, "docker_ram": 11 * guided.GIB, "host_ram": 11 * guided.GIB,
            "available_ram": 6 * guided.GIB, "disk_free": disk, "native": True, "gpu_nodes": []}
    mini = {**edge, "cpus": 16, "docker_ram": 30 * guided.GIB}
    assert guided.recommend(edge, "remote", True, "full") == {
        "concurrency": 1, "threads": 2, "rerank_threads": 4, "ocr_threads": 4,
        "rerank": True, "index": True}
    assert guided.recommend(mini, "remote", True, "full") == {
        "concurrency": 2, "threads": 4, "rerank_threads": 8, "ocr_threads": 8,
        "rerank": True, "index": True}
    hybrid = {**mini, "cpus": 8, "cpu_capacities": [382] * 4 + [889] * 3 + [1024]}
    assert guided.recommend(hybrid, "remote", True, "full") == {
        "concurrency": 1, "threads": 2, "rerank_threads": 4, "ocr_threads": 4,
        "rerank": True, "index": True}
    monkeypatch.setenv("DETHROTTLED_STACK_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(stack, "prerequisites", dict)
    monkeypatch.setattr(stack, "containers", lambda *a, **k: [])
    monkeypatch.setattr(stack, "check_port", lambda _: None)
    monkeypatch.setattr(guided, "inspect", lambda *a: edge)
    original = guided.run_guided
    responses = iter(["3", "", "", "", "", "", "", "", "", "y"])
    monkeypatch.setattr(guided, "run_guided",
                        lambda *a: original(*a, ask=lambda _: next(responses)))
    output = tmp_path / "plan.json"
    assert stack.main(["configure", "--project", "guided-test", "--port", "19096",
                       "--profile", "full", "--output", str(output)]) == 0
    assert not (tmp_path / "state").exists()
    plan = guided.load(output)
    assert plan[guided.PLAN_KEY]["profile"] == "full"
    assert plan["services"]["dnb"]["environment"]["DETHROTTLED_RENDER_CONCURRENCY"] == "1"
    api = plan["services"]["dethrottled"]["environment"]
    assert api["DETHROTTLED_RERANK_THREADS"] == api["DETHROTTLED_OCR_THREADS"] == "4"
    assert api["DETHROTTLED_EMBED_THREADS"] == "2"
    assert "authenticated REST/MCP separately" in capsys.readouterr().out

    context = tmp_path / "state" / "guided-test" / stack.__version__
    context.mkdir(parents=True)
    monkeypatch.setattr(stack, "prepare_context", lambda _: context)
    monkeypatch.setattr(stack, "run", lambda *a, **k: None)
    monkeypatch.setattr(stack, "inspect_status", lambda *a: {
        "selected_services": ["dnb"], "services": {"dnb": {"state": "ready"}}})
    assert stack.main(["up", "--config", str(output)]) == 0
    applied = json.loads((context / "managed.json").read_text())
    assert applied["services"]["dnb"]["environment"] == plan["services"]["dnb"]["environment"]
    settings = json.loads((context.parent / "project.json").read_text())
    assert settings["port"] == 19096 and settings["guided"] == plan
