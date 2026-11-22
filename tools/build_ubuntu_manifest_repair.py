"""Generate a small repair script for existing Ubuntu preview installs."""
import argparse
import ast
from base64 import b64decode, b64encode
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from ubuntu_preview_inventory import inventory_overlay, proton_profile_overlay

HEADER = r'''#!/bin/sh
set -eu
if [ "$#" -gt 0 ]; then
    root=$1
else
    root="$HOME/Games/@DESTINATION@"
@FIND_PREVIEW@
fi
python=python3
for bundled in "$root"/.linux-python/*/python/bin/python3; do
    if [ -x "$bundled" ]; then
        python=$bundled
        break
    fi
done
exec "$python" -I -B - "$root" <<'CLAN_WARS_REPAIR'
'''

FIND_LEGACY = '''    for newer in "$HOME/Games/Clan Wars Ubuntu Preview 2" "$HOME/Games/Clan Wars Ubuntu Preview 3"; do
        if [ -f "$newer/package-manifest.json" ]; then
            root=$newer
        fi
    done'''

REPAIR = r'''
from base64 import b64decode
from contextlib import ExitStack
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import os
import sys
from tempfile import NamedTemporaryFile


def replace(path, raw):
    with NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
    try:
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


root = Path(sys.argv[1]).resolve(strict=True)
manifest_path = root/'package-manifest.json'
if manifest_path.resolve(strict=True) != manifest_path:
    sys.exit('The package manifest is linked. Select the original install folder.')
with manifest_path.open('rb') as stream:
    original = stream.read(4*1024*1024+1)
if len(original)>4*1024*1024:
    sys.exit('Unexpected package manifest size.')
manifest = json.loads(original)
if manifest.get('build_id') not in BUILDS:
    sys.exit('This repair only applies to ' + TITLE + '.')
if UPDATE_CHANNEL is not None and manifest.get('linux_starter_update_channel') == UPDATE_CHANNEL:
    print('Linux Starter auto-updates are already enabled.')
    sys.exit(0)
rows = {row['path']:row for row in manifest['files']}
pending = {}
for name,(accepted,encoded) in PATCHES.items():
    target = root/name
    if target.resolve(strict=True) != target:
        sys.exit(f'Unexpected linked file: {name}')
    updated = b64decode(encoded,validate=True)
    new = sha256(updated).hexdigest()
    current = sha256(target.read_bytes()).hexdigest()
    allowed = (*accepted, new)
    if current not in allowed or rows.get(name, {}).get('sha256') not in allowed:
        sys.exit(f'This install has a different {name}. Use the installer or repair for that build.')
    if current != new:
        pending[target] = updated
    rows[name] = {'path':name,'bytes':len(updated),'sha256':new}
for name,encoded in ADDITIONS.items():
    target = root/name
    if target.resolve() != target or target.is_symlink():
        sys.exit(f'Unexpected linked file: {name}')
    updated = b64decode(encoded,validate=True)
    if target.exists() and target.read_bytes() != updated:
        sys.exit(f'This install already has a different {name}.')
    if not target.exists():
        pending[target] = updated
    rows[name] = {'path':name,'bytes':len(updated),'sha256':sha256(updated).hexdigest()}
if UPDATE_CHANNEL is not None:
    manifest.update(linux_starter_update_channel=UPDATE_CHANNEL, linux_starter_update_revision=0)
manifest['files'] = list(rows.values())
compact = (json.dumps(manifest,separators=(',',':'),ensure_ascii=True)+'\n').encode()
with ExitStack() as locks:
    state = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')/'ClanWarsUbuntuStarter'
    if state.exists():
        if state.is_symlink() or state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077:
            sys.exit('Clan Wars Starter data must be private to your Linux user.')
        for lock_name in ('starter.lock', 'steam-session.lock'):
            fd = os.open(state/lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            lock = locks.enter_context(os.fdopen(fd, 'rb'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                sys.exit('Close Clan Wars Starter and TRIBES 3 before applying this repair.')
    if manifest_path.read_bytes()!=original or len(compact)>4194304 or len(rows)>16384:
        sys.exit('The package changed or exceeds the repaired limits.')
    for target,raw in sorted(pending.items(),key=lambda item: item[0].suffix == '.sh'):
        replace(target,raw)
    if compact != original:
        replace(manifest_path,compact)
print(SUCCESS)
'''


def preview5_patch(installer):
    with installer.open('rb') as stream:
        header = stream.read(2 * 1024**2)
    source = header.split(b"<<'CLAN_WARS_PYTHON'\n", 1)[1].split(b'\nCLAN_WARS_PYTHON\n', 1)[0]
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(source).body
              if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id in ('PREVIEW', 'PREVIEW_RELEASE')}
    if values['PREVIEW_RELEASE']['revision'] != 70:
        raise ValueError('Expected the original Ubuntu Preview 5 r70 installer.')
    known = {
        'ubuntu_starter.py': ('78f586b1d0202d07e29fe67c7e45b164b4e183fcc1277184e0d15db6a9555ffa',
                              '603c6e660861e3fc17bf21763ee07b5f14856d8ecf00eb054a0d7fd6f345d0b1'),
        'ubuntu_join_worker.py': ('48bc86147e8624fadaa8546fd9e6d973f29d015862101775e6e52e17d0efc873',
                                  '19b4fd0014a32513d7d304fde5199e921b79c388ce619f706c8a38ebfb8f1318',
                                  '5645f0978ebdd1884eef5b0f3b241a91b0c1c21b4b4f626372cb80e69cd67f96'),
        'player_profile.py': ('bd04245db278c839d1dadc910602c6d07ebe6a93f9986864feaab8ec3ef6a2cc',),
    }
    patches = {}
    for name, accepted in known.items():
        old = b64decode(values['PREVIEW'][name], validate=True)
        if sha256(old).hexdigest() != accepted[0]:
            raise ValueError('Expected the original Ubuntu Preview 5 r70 installer.')
        new = (Path(__file__).resolve().parents[1]/name).read_text(encoding='utf-8').encode()
        if name == 'player_profile.py':
            new = proton_profile_overlay(old, new)
        patches[name] = (accepted, b64encode(new).decode('ascii'))
    return patches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--preview5-map-sync', action='store_true', help='Use the original Preview 5 .run as input')
    args = parser.parse_args()
    if args.preview5_map_sync:
        patches = preview5_patch(args.package)
        title = 'Clan Wars Ubuntu Preview 5 r70'
        builds = ('ClanWarsUbuntuNativePreview5R70',)
        success = 'Clan Wars Ubuntu join and player settings repaired. Reopen the Starter and select Join Game.'
    else:
        with ZipFile(args.package) as source:
            patches = {name:((old,),b64encode(updated).decode('ascii'))
                       for name,(old,updated) in inventory_overlay(source).items()}
        title = 'Clan Wars Ubuntu Preview'
        builds = tuple(f'ClanWarsUbuntuNativePreview{version}' for version in (1, 2, 3))
        success = 'Clan Wars Ubuntu package verification and preparation repaired. Reopen the Starter.'
    write_repair(args.output, title, builds, patches, success, find_legacy=not args.preview5_map_sync)


def write_repair(path, title, builds, patches, success, *, additions=None, channel=None, find_legacy=False):
    header = HEADER.replace('@DESTINATION@', title).replace('@FIND_PREVIEW@', FIND_LEGACY if find_legacy else '')
    settings = dict(TITLE=title, BUILDS=builds, SUCCESS=success, PATCHES=patches,
                    ADDITIONS=additions or {}, UPDATE_CHANNEL=channel)
    with path.open('x',encoding='utf-8',newline='\n') as output:
        output.write(header+''.join(f'{key} = {value!r}\n' for key,value in settings.items())+REPAIR+'\nCLAN_WARS_REPAIR\n')


if __name__=='__main__':
    main()
