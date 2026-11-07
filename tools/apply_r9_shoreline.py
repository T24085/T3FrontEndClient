"""Install the Damnation 2026 shoreline update into a complete Windows r9 Starter."""

import argparse
import json
from pathlib import Path, PurePosixPath
import tempfile
import time

from apply_r9_update import replace, sha


REVISION = 'Damnation2026-Shoreline-20261107-r1'
STARTER = 'Windows-20261107-r9'
MANIFEST = 'package-manifest.json'
MAP_LEVEL = 'content/Maps/Community/Damnation/Arena_Damnation_2026_P'
SHORELINE = 'content/Community/Damnation2026Shoreline/'
REPLACED = frozenset({'RELEASE-INFO.json', MAP_LEVEL+'.umap', MAP_LEVEL+'.uexp'})


def shoreline_file(name):
    path = PurePosixPath(name)
    return (path.as_posix() == name and name.startswith(SHORELINE) and len(path.parts) == 4
            and ':' not in name and '\\' not in name
            and path.suffix in {'.uasset', '.uexp', '.ubulk'})


def apply(package, update):
    package = Path(package).resolve(strict=True)
    update = Path(update).resolve(strict=True)
    plan = json.loads((update / 'update.json').read_bytes())
    files = plan['files']
    added = files.keys() - REPLACED
    if (plan['revision'] != REVISION or not REPLACED <= files.keys() or len(added) != 19
            or not all(shoreline_file(name) and files[name]['before'] is None for name in added)):
        raise ValueError('This is not a complete r9 shoreline update.')
    paths = [*sorted(files), MANIFEST]
    payload = update / 'payload'
    for name in paths:
        if package not in (package / name).resolve().parents or payload not in (payload / name).resolve().parents:
            raise ValueError('Unexpected linked path: ' + name)

    before_manifest = (package / MANIFEST).read_bytes()
    current = sha(before_manifest)
    installed = current == plan['manifest_after']
    if not installed and (current != plan['manifest_before'] or json.loads(before_manifest)['revision_id'] != STARTER):
        raise ValueError('Select the original complete Windows r9 Starter folder.')
    before = {MANIFEST: before_manifest}
    after = {MANIFEST: (payload / MANIFEST).read_bytes()}
    if sha(after[MANIFEST]) != plan['manifest_after']:
        raise ValueError('The update manifest is damaged.')
    for name, row in files.items():
        target = package / name
        old = target.read_bytes() if target.is_file() else None
        new = (payload / name).read_bytes()
        expected = row['after'] if installed else row['before']
        if (sha(old) if old is not None else None) != expected or sha(new) != row['after']:
            raise ValueError('Starter or update file differs from the verified release: ' + name)
        before[name], after[name] = old, new
    if installed:
        return 'This r9 Starter already has the shoreline update.'

    backup = Path(tempfile.mkdtemp(prefix='Starter-before-shoreline-' + time.strftime('%Y%m%d') + '-', dir=package.parent))
    for name, data in before.items():
        if data is not None:
            replace(backup / name, data)
    written = []
    try:
        for name in paths:
            replace(package / name, after[name])
            written.append(name)
        if any((package / name).read_bytes() != data for name, data in after.items()):
            raise OSError('Could not verify the updated Starter files.')
    except BaseException:
        for name in reversed(written):
            if before[name] is None:
                (package / name).unlink()
            else:
                replace(package / name, before[name])
        raise
    return 'r9 shoreline update installed. Reopen Community Starter. Backup: ' + str(backup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('starter_folder', type=Path)
    args = parser.parse_args()
    print(apply(args.starter_folder, Path(__file__).resolve().parent))
