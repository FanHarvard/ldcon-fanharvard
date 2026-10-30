#!/usr/bin/env python3
"""Select editable checkouts or PyPI wheels in an isolated site virtualenv."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
LIBRARIES = (
    ('experiment-core', 'v0.1.0', ''),
    ('agentbridge', 'v0.1.0', ''),
    ('ldcon', 'v0.2.2', '[web,instruments,analysis,agents]'),
)


def run(args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def editable_sources(root):
    root.mkdir(parents=True, exist_ok=True)
    sources = []
    for name, tag, extras in LIBRARIES:
        path = root / name
        url = 'https://github.com/FanHarvard/' + name + '.git'
        if not path.exists():
            run(['git', 'clone', '--branch', tag, url, path])
            run(['git', '-C', path, 'switch', '-c', 'codex/site-development'])
        else:
            # Never fetch, reset or overwrite an existing developer checkout.
            actual = subprocess.check_output(['git', '-C', path, 'remote', 'get-url', 'origin'], text=True).strip()
            if actual.removesuffix('.git') not in (url.removesuffix('.git'), 'git@github.com:FanHarvard/' + name):
                raise ValueError('Unexpected origin for ' + str(path))
            print('Keeping existing checkout:', path)
        sources += ['-e', str(path.resolve()) + extras]
    return sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--editable', action='store_true', help='Clone the three libraries and install with pip -e')
    mode.add_argument('--published', action='store_true', help='Replace editable installations with pinned PyPI releases')
    parser.add_argument('--venv', type=Path, default=REPO / '.venv')
    parser.add_argument('--libraries-root', type=Path, default=REPO / 'libraries')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error('Use Python 3.12 for this pinned site environment')
    env = args.venv.resolve()
    python = env / 'bin/python'
    if not env.exists():
        run([sys.executable, '-m', 'venv', env])
    elif not (env / 'pyvenv.cfg').is_file():
        parser.error('Destination exists and is not a virtualenv')
    if args.editable:
        sources = editable_sources(args.libraries_root.resolve())
        run([python, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple',
             '-c', REPO / 'constraints.txt', *sources])
    else:
        # Without force-reinstall, pip can retain a same-version editable package.
        run([python, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple',
             '--force-reinstall', '-r', REPO / 'requirements.txt'])
    run([python, '-m', 'pip', 'check'])
    run([python, REPO / 'ops/site.py', 'validate'])
    info = {'mode': 'editable' if args.editable else 'published',
            'libraries_root': str(args.libraries_root.resolve()) if args.editable else None}
    (env / 'ldcon-site-install.json').write_text(json.dumps(info, indent=2) + '\n')
    print('Ready:', python, '(no services started)')


if __name__ == '__main__':
    main()
