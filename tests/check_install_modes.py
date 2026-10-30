"""Integration test against public GitHub tags/PyPI, without hardware or services."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ('experiment-core', 'fanharvard-agentbridge', 'ldcon')


def run(*args):
    subprocess.run([str(v) for v in args], check=True)


def editable(python):
    return {r['name'].lower().replace('_', '-') for r in json.loads(subprocess.check_output(
        [str(python), '-m', 'pip', 'list', '--editable', '--format=json'], text=True))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=False)
    env, libs = root / 'venv', root / 'libraries'
    python = env / 'bin/python'
    common = [sys.executable, ROOT / 'ops/setup.py', '--venv', env, '--libraries-root', libs]
    run(*common, '--editable')
    assert set(PACKAGES) <= editable(python)
    # Keep uncommitted developer edits across both transitions.
    readmes = [libs / n / 'README.md' for n in ('ldcon', 'experiment-core', 'agentbridge')]
    for p in readmes:
        p.write_text(p.read_text() + '\nLocal install-mode preservation probe.\n')
    contents = {p: p.read_bytes() for p in readmes}
    run(*common, '--published')
    assert not (set(PACKAGES) & editable(python))
    run(*common, '--editable')
    assert set(PACKAGES) <= editable(python)
    assert all(p.read_bytes() == contents[p] for p in readmes)
    probe = "import ldcon,experiment_core,agentbridge,json; print(json.dumps([m.__file__ for m in (ldcon,experiment_core,agentbridge)]))"
    paths = json.loads(subprocess.check_output([str(python), '-c', probe], text=True))
    assert all(Path(p).resolve().is_relative_to(libs) for p in paths)
    run(python, ROOT / 'ops/site.py', 'init', root / 'state')
    run(python, ROOT / 'ops/site.py', 'units', root / 'state', root / 'units')
    print('Editable -> PyPI -> editable verified; edits preserved; no services started.')


if __name__ == '__main__':
    main()
