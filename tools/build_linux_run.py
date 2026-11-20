"""Wrap the official Linux ZIP in a single portable self-extracting installer."""
import argparse
from base64 import b64encode
from hashlib import file_digest, md5, sha256
import json
from pathlib import Path
import shutil
from zipfile import ZipFile
from ubuntu_preview_inventory import inventory_overlay

SOURCE = Path(__file__).resolve().parents[1]
PREVIEW_FILES = ('Start Community Starter.sh', 'Start Clan Wars Ubuntu.sh', 'ubuntu_starter.py',
                 'ubuntu_join_worker.py', 'linux_bootstrap.pyw', 'linux_launcher.py', 'UBUNTU PREVIEW.txt')
HEADER = r'''#!/bin/sh
set -eu
if [ "$(uname -m)" != x86_64 ]; then
    printf '%s\n' 'Clan Wars requires an x86-64 Linux PC or Steam Deck.' >&2
    exit 1
fi
archive=$(realpath -- "$0")
cache="${XDG_CACHE_HOME:-$HOME/.cache}/clan-wars-installer"
mkdir -p -- "$cache"
temporary=$(mktemp -d "$cache/run.XXXXXX")
trap 'rm -rf -- "$temporary"' EXIT
trap 'exit 1' HUP INT TERM
head -c @RUNTIME_END@ "$archive" | tail -c @RUNTIME_SIZE@ > "$temporary/python.tar.gz"
digest=$(sha256sum < "$temporary/python.tar.gz")
if [ "${digest%% *}" != '@RUNTIME_SHA@' ]; then
    printf '%s\n' 'Bundled Python is damaged. Download the installer again.' >&2
    exit 1
fi
tar -xzf "$temporary/python.tar.gz" -C "$temporary"
"$temporary/python/bin/python3" -I -B - "$archive" @ZIP_OFFSET@ @ZIP_SHA@ "$@" <<'CLAN_WARS_PYTHON'
@PYTHON_CODE@
CLAN_WARS_PYTHON
exit $?
'''


def build(package, proof_path, output, *, ubuntu_preview=False):
    proof = json.loads(proof_path.read_bytes())
    with package.open('rb') as payload:
        assert file_digest(payload, 'sha256').hexdigest() == proof['sha256']
    with ZipFile(package) as client:
        runtime = client.read('Linux Python.tar.gz')
        assert sha256(runtime).hexdigest() == client.read('Linux Python.sha256').decode().strip()
        manifest = json.loads(client.read('package-manifest.json'))
        assert len(manifest['community_maps']) == proof['maps']
        assert manifest['starter_update_revision'] == proof['revision']
        readers = inventory_overlay(client) if ubuntu_preview else {}
    code = (SOURCE/'linux_self_install.py').read_text(encoding='utf-8').rstrip()
    if ubuntu_preview:
        overlay = {name:b64encode((SOURCE/name).read_text(encoding='utf-8').encode()).decode('ascii')
                   for name in PREVIEW_FILES}
        overlay.update({name:b64encode(raw).decode('ascii') for name,(_,raw) in readers.items()})
        code = code.replace('PREVIEW = None', 'PREVIEW = '+repr(overlay), 1)
    values = {'RUNTIME_SIZE':str(len(runtime)), 'RUNTIME_SHA':sha256(runtime).hexdigest(),
              'ZIP_SHA':proof['sha256'], 'PYTHON_CODE':code}
    template = HEADER
    for name, value in values.items():
        template = template.replace('@'+name+'@', value)
    number = '0' * 16
    header_length = len(template.replace('@RUNTIME_END@',number).replace('@ZIP_OFFSET@',number).encode())
    offset = header_length + len(runtime)
    # Use leading spaces to reserve a constant number of bytes without shell octal parsing.
    header = template.replace('@RUNTIME_END@',f'{offset:16d}').replace('@ZIP_OFFSET@',f'{offset:16d}').encode()
    assert len(header) == header_length
    partial = output.with_suffix('.run.partial')
    if output.exists():
        raise FileExistsError(output)
    with partial.open('xb') as target, package.open('rb') as source:
        target.write(header)
        target.write(runtime)
        shutil.copyfileobj(source,target,4*1024**2)
    digest = sha256()
    drive_digest = md5(usedforsecurity=False)
    with partial.open('rb') as raw:
        assert raw.read(len(header)) == header
        assert raw.read(len(runtime)) == runtime
        digest.update(header)
        digest.update(runtime)
        drive_digest.update(header)
        drive_digest.update(runtime)
        payload_hash = sha256()
        while chunk := raw.read(4*1024**2):
            digest.update(chunk)
            drive_digest.update(chunk)
            payload_hash.update(chunk)
        assert payload_hash.hexdigest() == proof['sha256']
    with ZipFile(partial) as client:
        assert json.loads(client.read('package-manifest.json')) == manifest
    partial.rename(output)
    return {'name':output.name,'bytes':output.stat().st_size,'sha256':digest.hexdigest(),
            'md5':drive_digest.hexdigest(),'revision':proof['revision'],'maps':proof['maps']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package','package-proof','output','proof'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--ubuntu-preview', action='store_true')
    args = parser.parse_args()
    result = build(args.package,args.package_proof,args.output,ubuntu_preview=args.ubuntu_preview)
    args.proof.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
