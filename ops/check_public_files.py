"""Check the tracked-file boundary without printing credential values."""
import json
from pathlib import Path
import re
import subprocess

import yaml

paths = subprocess.check_output(['git', 'ls-files', '-z'], text=True).split('\0')
for name in filter(None, paths):
    path = Path(name)
    if path.is_symlink():
        raise SystemExit('Public symlink rejected: ' + name)
    if (any(p in {'libraries', '.venv', 'private', 'state', 'releases', 'jobs', 'logs', 'boxes'} for p in path.parts)
            or path.suffix in {'.pem', '.key', '.p12', '.pfx', '.env', '.jsonl', '.sqlite3'}
            or path.name in {'.env', '.pypirc', 'web-server.json', 'credentials.env'}):
        raise SystemExit('Private/runtime path rejected: ' + name)
    if path.parts[0] != 'site':
        continue
    def check(value, location):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ('allow_output', 'writes_enabled') and item is not False:
                    raise SystemExit('Initial output must remain disabled: ' + location)
                if key in ('session_id', 'recovery_artifact') and item:
                    raise SystemExit('Runtime identity/artifact rejected: ' + location)
                if re.search(r'(^|_)(password|secret|credential|token|api_key|webhook)($|_)', key, re.I) and not key.endswith('_env') and item:
                    raise SystemExit('Credential-like key rejected: ' + location + '.' + key)
                check(item, location + '.' + key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                check(item, location + f'[{i}]')
        elif isinstance(value, str) and re.search(r'/s/[A-Za-z0-9_-]{24,}|https?://[^/\s]+:[^/@\s]+@|webhook\.office|hooks\.slack', value):
            raise SystemExit('Credential-like URL rejected: ' + location)
    check(yaml.safe_load(path.read_text()), name)
print('Tracked configuration contains no credential values or runtime state.')
