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
    env = stack.clean_environment(19087)
    assert 'COMPOSE_FILE' not in env and 'DETHROTTLED_EXA_API_KEY' not in env
    assert env['DETHROTTLED_BIND'] == '127.0.0.1'
    assert env['DETHROTTLED_PORT'] == '19087'


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
