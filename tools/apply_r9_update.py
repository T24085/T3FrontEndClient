"""Apply the Windows r9 runtime update to a verified r8 Starter folder."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


REVISION = 'Windows-20261107-r9'
BASE = 'Windows-20261107-r8'
PAYLOAD = frozenset({
    'client.py', 'desktop_launcher.py', 'lua/client.lua', 'server_access.py',
    'server_access_contract.py', 'server-access.json', 'README-FIRST.txt',
    'RELEASE-INFO.json', 'SOURCE-INFO.json',
})


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def replace(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.starter-r9-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply(package, update):
    package = Path(package).resolve(strict=True)
    update = Path(update).resolve(strict=True)
    plan = json.loads((update / 'update.json').read_bytes())
    if plan['revision'] != REVISION or set(plan['files']) != PAYLOAD:
        raise ValueError('This is not the r9 Starter update.')
    manifest = 'package-manifest.json'
    before_manifest = (package / manifest).read_bytes()
    if sha(before_manifest) == plan['manifest_after']:
        return 'This Starter already has r9.'
    if sha(before_manifest) != plan['manifest_before'] or json.loads(before_manifest)['revision_id'] != BASE:
        raise ValueError('Select an unmodified, complete Windows r8 Starter folder.')
    before = {manifest: before_manifest}
    after = {manifest: (update / 'payload' / manifest).read_bytes()}
    if sha(after[manifest]) != plan['manifest_after']:
        raise ValueError('The update manifest is damaged.')
    for name, expected in plan['files'].items():
        target = package / name
        if package not in target.resolve().parents:
            raise ValueError('Unexpected linked Starter path: ' + name)
        original = target.read_bytes() if target.is_file() else None
        payload = (update / 'payload' / name).read_bytes()
        if (sha(original) if original is not None else None) != expected['before'] or sha(payload) != expected['after']:
            raise ValueError('Starter or update file differs from the verified release: ' + name)
        before[name] = original
        after[name] = payload

    backup = Path(tempfile.mkdtemp(prefix='Starter-before-r9-' + time.strftime('%Y%m%d') + '-', dir=package.parent))
    for name, original in before.items():
        if original is not None:
            replace(backup / name, original)
    written = []
    try:
        for name in sorted(PAYLOAD) + [manifest]:
            replace(package / name, after[name])
            written.append(name)
        if any((package / name).read_bytes() != data for name, data in after.items()):
            raise OSError('Could not verify the updated Starter files.')
    except BaseException:
        for name in reversed(written):
            original = before[name]
            if original is None:
                (package / name).unlink()
            else:
                replace(package / name, original)
        raise
    return 'r9 installed. Reopen Community Starter. Backup: ' + str(backup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('starter_folder', type=Path)
    args = parser.parse_args()
    print(apply(args.starter_folder, Path(__file__).resolve().parent))
