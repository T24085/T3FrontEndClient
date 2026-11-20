"""Generate a small repair script for existing Ubuntu preview installs."""
import argparse
from base64 import b64encode
from pathlib import Path
from zipfile import ZipFile

from ubuntu_preview_inventory import inventory_overlay

HEADER = r'''#!/bin/sh
set -eu
if [ "$#" -gt 0 ]; then
    root=$1
else
    root="$HOME/Games/Clan Wars Ubuntu Preview"
    for newer in "$HOME/Games/Clan Wars Ubuntu Preview 2" "$HOME/Games/Clan Wars Ubuntu Preview 3"; do
        if [ -f "$newer/package-manifest.json" ]; then
            root=$newer
        fi
    done
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

REPAIR = r'''
from base64 import b64decode
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
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


root = Path(sys.argv[1]).resolve()
manifest_path = root/'package-manifest.json'
with manifest_path.open('rb') as stream:
    original = stream.read(4*1024*1024+1)
if len(original)>4*1024*1024:
    sys.exit('Unexpected package manifest size. Use the Ubuntu Preview 3 installer.')
manifest = json.loads(original)
if manifest.get('build_id') not in ('ClanWarsUbuntuNativePreview1','ClanWarsUbuntuNativePreview2','ClanWarsUbuntuNativePreview3'):
    sys.exit('This repair only applies to the native Ubuntu preview.')
rows = {row['path']:row for row in manifest['files']}
pending = {}
for name,(old,encoded) in PATCHES.items():
    target = root/name
    if target.resolve(strict=True) != target:
        sys.exit(f'Unexpected linked file: {name}')
    updated = b64decode(encoded,validate=True)
    new = sha256(updated).hexdigest()
    current = sha256(target.read_bytes()).hexdigest()
    if current not in (old,new) or rows[name]['sha256'] not in (old,new):
        sys.exit(f'This preview has a different {name}. Use the Ubuntu Preview 3 installer.')
    if current != new:
        pending[target] = updated
    rows[name] = {'path':name,'bytes':len(updated),'sha256':new}
manifest['files'] = list(rows.values())
compact = (json.dumps(manifest,separators=(',',':'),ensure_ascii=True)+'\n').encode()
if manifest_path.read_bytes()!=original or len(compact)>4194304 or len(rows)>16384:
    sys.exit('The package changed or exceeds the repaired limits.')
for target,raw in pending.items():
    replace(target,raw)
if compact != original:
    replace(manifest_path,compact)
print('Clan Wars Ubuntu package verification and preparation repaired. Reopen the Starter.')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    with ZipFile(args.package) as source:
        patches = {name:(old,b64encode(updated).decode('ascii'))
                   for name,(old,updated) in inventory_overlay(source).items()}
    with args.output.open('x',encoding='utf-8',newline='\n') as output:
        output.write(HEADER+'PATCHES = '+repr(patches)+'\n'+REPAIR+'\nCLAN_WARS_REPAIR\n')


if __name__=='__main__':
    main()
