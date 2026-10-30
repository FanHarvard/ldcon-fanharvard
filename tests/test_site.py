import importlib.util
import json
import os
from pathlib import Path
import socket

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('site_ops', ROOT / 'ops/site.py')
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Offline preparation attempted network I/O')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'getaddrinfo', denied)


def test_initialize_offline_and_keep_credentials_local(tmp_path):
    state = tmp_path / 'state'
    assert site.initialize(state)['cards'] == 78
    for n in site.LASERS:
        value = yaml.safe_load((state / 'lasers' / n / 'config/lasers' / (n + '.yaml')).read_text())
        assert value['allow_output'] is False
    private = state / 'private/credentials.env'
    assert private.stat().st_mode & 0o777 == 0o600
    assert private.parent.stat().st_mode & 0o777 == 0o700
    values = [line.split('=', 1)[1] for line in private.read_text().splitlines()]
    assert len(values) == len(set(values)) == 4
    assert all(len(v) >= 32 for v in values)
    assert not (state / 'private/physical-locks.json').exists()


def test_existing_state_is_not_overwritten(tmp_path):
    state = tmp_path / 'state'
    site.initialize(state)
    old = (state / 'private/credentials.env').read_bytes()
    with pytest.raises(FileExistsError):
        site.initialize(state)
    assert (state / 'private/credentials.env').read_bytes() == old


def test_symlink_destination_is_not_reused(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(original, target_is_directory=True)
    with pytest.raises(FileExistsError):
        site.initialize(alias)
    assert list(original.iterdir()) == []


def test_init_refuses_state_inside_git_checkout(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    monkeypatch.setattr(site, 'REPO', repo)
    monkeypatch.setattr('sys.argv', ['site.py', 'init', str(repo / 'runtime')])
    with pytest.raises(SystemExit):
        site.main()
    assert not (repo / 'runtime').exists()


def test_unknown_placeholder_fails():
    with pytest.raises(ValueError, match='Unresolved'):
        site.expand({'endpoint': '${OTHER_ROOT}/secret'}, Path('/tmp/state'))


def test_invalid_physical_policy_is_rejected(tmp_path):
    state = tmp_path / 'state'
    site.initialize(state)
    path = state / 'device-owners/cld1015-M01343851/config.json'
    config = json.loads(path.read_text())
    config['port'] = -1
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        site.validate_state(state)


def test_units_use_current_env_and_preserve_job_lifetime(tmp_path):
    state = tmp_path / 'state with spaces'
    site.initialize(state)
    output = tmp_path / 'units'
    assert site.units(state, output) == 19
    jobs = (output / 'ldcon-fh-sr422-jobs.service').read_text()
    assert 'KillMode=process' in jobs
    assert str(Path(site.sys.executable).absolute()) in jobs
    assert 'LDCON_SHARED_ROOTS' in jobs
    assert 'LDCON_PRIVATE_ROOTS' in jobs
    assert 'LDCON_AGENTBRIDGE_PUBLIC' in jobs
    assert 'private/credentials.env' in jobs
    for line in (state / 'private/credentials.env').read_text().splitlines():
        assert line.split('=', 1)[1] not in jobs
    with pytest.raises(FileExistsError):
        site.units(state, output)


def test_fleet_registry_and_owner_commands_are_local(tmp_path):
    state = tmp_path / 'state'
    site.initialize(state)
    rows = site.services(state, Path('/venv/bin/python'))
    assert all(row['argv'][0] == '/venv/bin/python' for row in rows.values())
    assert all(row['argv'][1] == '-m' and row['argv'][2].startswith('ldcon.') for row in rows.values())
    registry = json.loads((state / 'dashboard/registry.json').read_text())
    assert all(row['origin'].startswith('http://127.0.0.1:') for row in registry['services'])


def test_unit_path_escaping():
    assert site.systemd_quote('/tmp/a%b') == '"/tmp/a%%b"'
    assert site.systemd_quote('/tmp/$x') == '"/tmp/$x"'
    assert site.systemd_quote('/tmp/$x', command=True) == '"/tmp/$$x"'
    with pytest.raises(ValueError):
        site.systemd_quote('/tmp/a\nExecStart=/other')
