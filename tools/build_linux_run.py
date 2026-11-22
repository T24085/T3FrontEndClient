"""Wrap the official Linux ZIP in a single portable self-extracting installer."""
import argparse
from base64 import b64encode
from hashlib import file_digest, md5, sha256
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile
from ubuntu_preview_inventory import inventory_overlay, proton_profile_overlay

SOURCE = Path(__file__).resolve().parents[1]
# Keep the r59 payload pinned; overlay the canonical cache only for Ubuntu.
PREVIEW_CACHE_BASE_SHA256 = 'ef4d3662d7982df24a3f3c43f38bf1f230e15e4568c49a428981fd8d3b2e78f7'
PREVIEW_FILES = ('Start Community Starter.sh', 'Start Clan Wars Ubuntu.sh', 'ubuntu_starter.py',
                 'ubuntu_join_worker.py', 'linux_bootstrap.pyw', 'linux_launcher.py', 'UBUNTU PREVIEW.txt',
                 'ubuntu_startup.py', 'starter_update.py', 'starter_update_signing.py', 'direct_update_contract.py')
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


def signed_preview_overlay(root, manifest):
    sys.path.insert(0, str(SOURCE))
    try:
        from starter_update import DIRECT_CHANNEL, INDEX, LINUX_CHANNEL, MAX_INDEX, decode_index
    finally:
        sys.path.pop(0)
    with (root/INDEX).open('rb') as index_file:
        raw = index_file.read(MAX_INDEX+1)
    index = decode_index(raw, channel=DIRECT_CHANNEL)
    files = index['files']
    names = set(files)
    if (index['revision'] < 70 or index['revision'] <= manifest['starter_update_revision']
            or 'direct_host_contract' not in manifest):
        raise ValueError('The Ubuntu preview requires a newer signed Direct update with the expanded inventory readers.')
    inventory = {row['path'] for row in manifest['files']}
    frozen = {name for entries in manifest['map_runtime'].values() for name in entries}
    needed = {'verified_file_cache.py', 'client_preparation.py', 'community_game.py', 'player_profile.py'}
    if (not names <= inventory or names & (frozen | {'bulk_asset_cache.py'})
            or not (set(manifest.get('starter_update_files', [])) | needed) <= names):
        raise ValueError('The signed Direct update does not match this Ubuntu package.')
    overlay = {}
    for name, row in files.items():
        with (root/f"starter-file-{row['sha256']}.bin").open('rb') as source:
            payload = source.read(row['bytes']+1)
        if (len(payload), sha256(payload).hexdigest()) != (row['bytes'], row['sha256']):
            raise ValueError(f'Signed update file failed verification: {name}')
        if name.endswith('.py'):
            compile(payload, name, 'exec')
        overlay[name] = payload
    return overlay, {'revision':index['revision'], 'files':sorted(names), 'index_sha256':sha256(raw).hexdigest(),
                     'linux_update_channel': LINUX_CHANNEL}


def build(package, proof_path, output, *, ubuntu_preview=False, signed_update=None):
    if signed_update is not None and not ubuntu_preview:
        raise ValueError('A signed update can only be embedded in an Ubuntu preview.')
    proof = json.loads(proof_path.read_bytes())
    with package.open('rb') as payload:
        assert file_digest(payload, 'sha256').hexdigest() == proof['sha256']
    with ZipFile(package) as client:
        runtime = client.read('Linux Python.tar.gz')
        assert sha256(runtime).hexdigest() == client.read('Linux Python.sha256').decode().strip()
        manifest = json.loads(client.read('package-manifest.json'))
        assert len(manifest['community_maps']) == proof['maps']
        assert manifest['starter_update_revision'] == proof['revision']
        readers = inventory_overlay(client, signed_inventory=signed_update is not None) if ubuntu_preview else {}
        if ubuntu_preview and sha256(client.read('bulk_asset_cache.py')).hexdigest() != PREVIEW_CACHE_BASE_SHA256:
            raise ValueError('Review the changed Ubuntu package cache module.')
        signed_files, release = signed_preview_overlay(signed_update, manifest) if signed_update else ({}, None)
    code = (SOURCE/'linux_self_install.py').read_text(encoding='utf-8').rstrip()
    if ubuntu_preview:
        overlay = {name:b64encode((SOURCE/name).read_text(encoding='utf-8').encode()).decode('ascii')
                   for name in PREVIEW_FILES}
        overlay.update({name:b64encode(raw).decode('ascii') for name,(_,raw) in readers.items()})
        overlay['bulk_asset_cache.py'] = b64encode((SOURCE/'bulk_asset_cache.py').read_bytes()).decode('ascii')
        if signed_files.keys() & overlay.keys():
            raise ValueError('A signed update file conflicts with an Ubuntu-specific overlay.')
        overlay.update({name:b64encode(raw).decode('ascii') for name,raw in signed_files.items()})
        if release is not None:
            source_profile = (SOURCE/'player_profile.py').read_text(encoding='utf-8').encode()
            profile = proton_profile_overlay(signed_files['player_profile.py'], source_profile)
            overlay['player_profile.py'] = b64encode(profile).decode('ascii')
        code = code.replace('PREVIEW = None', 'PREVIEW = '+repr(overlay), 1)
        if release is not None:
            release['preview'] = 7
            code = code.replace('PREVIEW_RELEASE = None', 'PREVIEW_RELEASE = '+repr(release), 1)
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
    result = {'name':output.name,'bytes':output.stat().st_size,'sha256':digest.hexdigest(),
              'md5':drive_digest.hexdigest(),'revision':proof['revision'],'maps':proof['maps']}
    if release is not None:
        result.update(base_revision=proof['revision'], revision=release['revision'], preview=release['preview'],
                      signed_update_index_sha256=release['index_sha256'], signed_files=len(release['files']),
                      signed_file_platform_overrides=['player_profile.py'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package','package-proof','output','proof'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--ubuntu-preview', action='store_true')
    parser.add_argument('--signed-update', type=Path, help='Directory containing the verified Direct feed snapshot')
    args = parser.parse_args()
    result = build(args.package,args.package_proof,args.output,ubuntu_preview=args.ubuntu_preview,
                   signed_update=args.signed_update)
    args.proof.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
