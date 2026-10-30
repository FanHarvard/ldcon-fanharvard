#!/usr/bin/env python3
"""Stage and validate site configuration; render commands without starting services."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shlex
import sys
import tempfile

import yaml

REPO = Path(__file__).resolve().parents[1]
LASERS = ('sr422', 'sr1092', 'thf685')
CREDENTIAL_KEYS = ('LDCON_INSTRUMENT_TOKEN', 'LDCON_PROJECTION_SR422',
                   'LDCON_PROJECTION_SR1092', 'LDCON_PROJECTION_THF685')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def expand(value, state):
    if isinstance(value, dict):
        return {k: expand(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, state) for v in value]
    if isinstance(value, str):
        value = value.replace('${STATE_ROOT}', str(state))
        if '${' in value:
            raise ValueError('Unresolved configuration variable')
    return value


def render(state, source=REPO / 'site'):
    for path in sorted(source.rglob('*')):
        if not path.is_file():
            continue
        if path.is_symlink() or path.suffix not in ('.yaml', '.json'):
            raise ValueError('Only regular YAML/JSON configuration files may be staged')
        target = state / path.relative_to(source)
        data = expand(yaml.safe_load(path.read_text()), state)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == '.json':
            write_json(target, data)
        else:
            target.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    for laser in LASERS:
        write_json(state / 'lasers' / laser / 'laser-layout.json',
                   {'schema': 'ldcon.single-laser-layout.v1', 'laser_id': laser})
    write_json(state / 'dashboard/registry.json', {
        'services': [{'id': n, 'label': n, 'origin': f'http://127.0.0.1:{8767 + i * 10}',
                      'state_file': str(state / 'lasers' / n / 'web-server.json'),
                      'lasers': [{'id': n, 'name': n}]} for i, n in enumerate(LASERS)],
        'telemetry_endpoint': 'udp://127.0.0.1:8094'})


def validate_state(state):
    from ldcon.core.interface_schema import InterfaceRepository
    from ldcon.owners.instrument_owner import validate_config as instrument_config
    from ldcon.owners.cld_owner import validate_config as cld_config
    from ldcon.owners.device_registry import validate_config as registry_config
    from ldcon.owners.monitor_owner import startup_policy
    from ldcon.owners.dlcpro_deployment import commissioning_issues
    from ldcon.web.web_fleet import read_registry
    count = 0
    for n in LASERS:
        bundle = InterfaceRepository(state / 'lasers' / n).assignment(n)
        count += sum(len(deck['document']['cards']) for deck in bundle['deck_definitions'])
    for p in (state / 'instrument-owners').glob('*/config.json'):
        instrument_config(json.loads(p.read_text()))
    cld_config(json.loads((state / 'device-owners/cld1015-M01343851/config.json').read_text()))
    registry_config(json.loads((state / 'instrument-owners/registry.json').read_text()))
    native = state / 'device-owners/esp32servocon-sr1092/config.json'
    config = json.loads(native.read_text())
    laser = yaml.safe_load(Path(config['native_assembly']['laser_file']).read_text())
    startup_policy(config, laser)
    config = json.loads((state / 'lasers/thf685/dlcpro-owner.json').read_text())
    lasers = [yaml.safe_load(Path(p).read_text()) for p in config['laser_files']]
    issues = commissioning_issues(config, lasers)
    unexpected = [v for v in issues if not v.endswith(': output authority is disabled')]
    if unexpected:
        raise ValueError('DLC configuration: ' + '; '.join(unexpected))
    read_registry(state / 'dashboard/registry.json')
    return {'lasers': list(LASERS), 'cards': count, 'hardware_io': False}


def initialize(state):
    # Never overwrite a deployment, follow an existing symlink or reuse its keys.
    state.mkdir(parents=True, exist_ok=False, mode=0o700)
    render(state)
    result = validate_state(state)
    private = state / 'private'
    private.mkdir(mode=0o700)
    fd = os.open(private / 'credentials.env', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as out:
        for key in CREDENTIAL_KEYS:
            out.write(key + '=' + secrets.token_urlsafe(48) + '\n')
    (state / 'physical-locks').mkdir()
    (state / 'agentbridge').mkdir()
    (state / 'adaptive-control').mkdir(mode=0o700)
    (private / 'evidence').mkdir(mode=0o700)
    write_json(state / 'site-install.json', {'schema': 1, 'source': str(REPO), 'initialized': True})
    return result


def services(state, python):
    """All roles use the same interpreter; no implementation lives in this repo."""
    result = {}
    def add(name, module, *args, laser=None, jobs=False):
        result[name] = {'argv': [str(python), '-m', module, *map(str, args)],
                        'laser': laser, 'jobs': jobs}
    for p in sorted((state / 'instrument-owners').glob('*/config.json')):
        add(p.parent.name, 'ldcon.owners.instrument_owner', '--config', p)
    add('registry', 'ldcon.owners.device_registry', '--config', state / 'instrument-owners/registry.json')
    add('cld1015', 'ldcon.owners.cld_owner', '--config', state / 'device-owners/cld1015-M01343851/config.json')
    for name in ('esp32servocon-sr1092', 'scope-sr422-sr1092'):
        add(name, 'ldcon.owners.monitor_owner', '--config', state / 'device-owners' / name / 'config.json',
            laser='sr1092' if name.startswith('esp32') else None)
    add('sr422-instruments', 'ldcon.owners.instrument_service', '--config', state / 'device-owners/sr422/config.json', laser='sr422')
    add('thf685-dlc', 'ldcon.owners.dlcpro_service', '--config', state / 'lasers/thf685/dlcpro-owner.json',
        '--allow-hardware', laser='thf685')
    for i, n in enumerate(LASERS):
        root = state / 'lasers' / n
        add(n + '-jobs', 'ldcon.jobs.job_service', '--state-dir', root, laser=n, jobs=True)
        add(n + '-web', 'ldcon.web.web_server', '--state-dir', root, '--state-file', root / 'web-server.json',
            '--host', '127.0.0.1', '--port', 8767 + i * 10, laser=n)
        add(n + '-notifications', 'ldcon.agents.fallback_service', '--web-root', root,
            '--notification-root', root / 'notifications', '--server-file', root / 'web-server.json',
            '--host', '127.0.0.1', '--port', 8768 + i * 10, laser=n)
    add('fleet', 'ldcon.web.web_fleet', '--registry', state / 'dashboard/registry.json',
        '--state-file', state / 'dashboard/web-server.json', '--host', '127.0.0.1', '--port', 8086)
    return result


def systemd_quote(value, *, command=False):
    # Systemd specifier and dollar expansion are distinct from shell quoting.
    value = str(value)
    if any(c in value for c in ('\n', '\r', '\x00')):
        raise ValueError('Newlines/NUL are not valid in unit paths')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return '"' + (value.replace('$', '$$') if command else value) + '"'


def units(state, output):
    # sys.executable must retain its venv path (resolve() would select the base Python).
    python = Path(sys.executable).absolute()
    bridge = Path(next(iter(importlib.util.find_spec('agentbridge').submodule_search_locations)))
    from ldcon.core.paths import checkout_root
    core = Path(next(iter(importlib.util.find_spec('experiment_core').submodule_search_locations)))
    shared = [str(REPO), str(checkout_root()), str(core.parent), str(bridge.parent)]
    output.mkdir(parents=True, exist_ok=False)
    for name, service in services(state, python).items():
        env = {'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
               'LDCON_JOB_LAUNCHER': 'service', 'AGENTBRIDGE_HOME': str(state / 'agentbridge'),
               'LDCON_AGENTBRIDGE_HUB': str(bridge / 'agent_hub.py'),
               'LDCON_AGENTBRIDGE_SCRIPT': str(bridge / 'agent_msg.py'),
               'LDCON_AGENTBRIDGE_PUBLIC': str(state / 'agentbridge'),
               'LDCON_ADAPTIVE_ROOT': str(state / 'adaptive-control'),
               'LDCON_SHARED_ROOTS': json.dumps(shared),
               'LDCON_PRIVATE_ROOTS': json.dumps([str(state / 'private'), str(state / 'adaptive-control')]),
               'LDCON_PHYSICAL_LOCK_MANIFEST': str(state / 'private/physical-locks.json')}
        laser = service['laser']
        if laser:
            env.update(LDCON_BACKGROUND_LASER_ID=laser,
                       LDCON_NOTIFICATION_PORT=str(8768 + LASERS.index(laser) * 10))
        text = ['[Unit]', 'Description=FanHarvard LDCon ' + name, 'After=network-online.target', '',
                '[Service]', 'Type=simple', 'WorkingDirectory=' + str(state).replace('%', '%%'),
                *('Environment=' + systemd_quote(k + '=' + v) for k, v in env.items()),
                'EnvironmentFile=' + str(state / 'private/credentials.env').replace('%', '%%'),
                'EnvironmentFile=-' + str(state / 'private/local.env').replace('%', '%%'),
                'ExecStart=' + ' '.join(systemd_quote(v, command=True) for v in service['argv']),
                'KillMode=' + ('process' if service['jobs'] else 'control-group'),
                'Restart=no', 'UMask=0077', 'TimeoutStopSec=30', '', '[Install]', 'WantedBy=default.target', '']
        (output / ('ldcon-fh-' + name + '.service')).write_text('\n'.join(text))
    return len(services(state, python))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('validate', help='Validate the repository offline in temporary storage')
    for name in ('init', 'plan', 'units'):
        cmd = commands.add_parser(name)
        cmd.add_argument('state', type=Path, help='Separate runtime root outside this repository')
        if name == 'units':
            cmd.add_argument('destination', type=Path, help='New directory for reviewable user-unit drafts')
    args = parser.parse_args()
    if args.command == 'validate':
        with tempfile.TemporaryDirectory(prefix='ldcon-site-') as tmp:
            state = Path(tmp)
            render(state)
            print(json.dumps(validate_state(state)))
        return
    raw = args.state.expanduser().absolute()
    if raw.is_symlink():
        parser.error('State root must not be a symlink')
    state = raw.resolve()
    if state == REPO or REPO in state.parents:
        parser.error('Runtime state and credentials must be outside the repository')
    if args.command == 'init':
        print(json.dumps(initialize(state)))
        print('Prepared disabled configuration. Credentials stored locally; no services started.')
    else:
        validate_state(state)
        if args.command == 'plan':
            for name, row in services(state, Path(sys.executable).absolute()).items():
                print(name + ': ' + shlex.join(row['argv']))
        else:
            print('Rendered', units(state, args.destination.resolve()), 'user units; nothing installed or started.')


if __name__ == '__main__':
    main()
