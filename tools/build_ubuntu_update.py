"""Prepare the one-time Preview 6 upgrade or the files for a signed Linux update."""
import argparse
import ast
from base64 import b64decode, b64encode
import json
from pathlib import Path
import sys
import time
from zipfile import ZipFile

from build_linux_run import SOURCE, signed_preview_overlay
from build_starter_update import sign_index
from build_ubuntu_manifest_repair import write_repair
from ubuntu_preview_inventory import proton_profile_overlay

sys.path.insert(0, str(SOURCE))
from direct_update_contract import LINUX_INDEX
from starter_update import (LINUX_CHANNEL, LINUX_CHUNK_BYTES, MAX_FILE, MAX_TOTAL, UPDATE_CHANNELS,
                            decode_index, encoded, sha)

FIRST_UPDATER = '2e5692114053e3b753f018230048e2ee30c65cd6e2f22bb857f740e51d24cdc4'


def base_data(installer):
    with installer.open('rb') as stream:
        header = stream.read(4 * 1024**2)
    marker = b"<<'CLAN_WARS_PYTHON'\n"
    source = header.split(marker, 1)[1].split(b'\nCLAN_WARS_PYTHON\n', 1)[0]
    data = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(source).body
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ('PREVIEW', 'PREVIEW_RELEASE')}
    return data['PREVIEW_RELEASE'], data['PREVIEW']


def source_bytes(name):
    return (SOURCE/name).read_text(encoding='utf-8').encode()


def enable(installer, output):
    release, overlay = base_data(installer)
    if (release['preview'], release['revision']) != (6, 74):
        raise ValueError('Expected the Preview 6 r74 full installer.')
    replacements = ('starter_update.py', 'starter_update_signing.py', 'direct_update_contract.py',
                    'ubuntu_starter.py', 'Start Community Starter.sh')
    patches = {}
    with ZipFile(installer) as archive:
        for name in replacements:
            old = b64decode(overlay[name], validate=True) if name in overlay else archive.read(name)
            accepted = (sha(old), FIRST_UPDATER) if name == 'starter_update.py' else (sha(old),)
            patches[name] = (accepted, b64encode(source_bytes(name)).decode('ascii'))
    write_repair(output, 'Clan Wars Ubuntu Preview 6 r74', ('ClanWarsUbuntuNativePreview6R74',), patches,
                 'Linux Starter auto-updates enabled. Reopen Clan Wars to check for an update.',
                 additions={'ubuntu_startup.py':b64encode(source_bytes('ubuntu_startup.py')).decode('ascii')},
                 channel=LINUX_CHANNEL, bootstrap=2)


def feed(installer, snapshot, output, revision, certificate):
    with ZipFile(installer) as archive:
        manifest = json.loads(archive.read('package-manifest.json'))
    base_release, overlay = base_data(installer)
    files, current = signed_preview_overlay(snapshot, manifest)
    if current['revision'] < base_release['revision']:
        raise ValueError('The feed cannot downgrade the bundled Windows components.')
    files['player_profile.py'] = proton_profile_overlay(files['player_profile.py'], source_bytes('player_profile.py'))
    for name in ('ubuntu_starter.py', 'ubuntu_join_worker.py', 'linux_launcher.py', 'linux_bootstrap.pyw'):
        if name not in overlay:
            raise ValueError(f'Ubuntu base is missing {name}.')
        files[name] = source_bytes(name)
    if (not 1 <= revision < 2**31 or not files.keys() <= UPDATE_CHANNELS[LINUX_CHANNEL][1]
            or any(not 0 < len(raw) <= MAX_FILE for raw in files.values())
            or sum(map(len, files.values())) > MAX_TOTAL):
        raise ValueError('Linux update exceeds the supported revision or file limits.')
    rows, blobs = {}, {}
    for name, raw in files.items():
        if name.endswith(('.py', '.pyw')):
            compile(raw, name, 'exec')
        pinned = sha(raw)
        row = rows[name] = {'bytes':len(raw), 'sha256':pinned}
        if len(raw) <= LINUX_CHUNK_BYTES:
            blobs[pinned] = raw
            continue
        row['chunks'] = []
        for offset in range(0, len(raw), LINUX_CHUNK_BYTES):
            part = raw[offset:offset + LINUX_CHUNK_BYTES]
            part_sha = sha(part)
            blobs[part_sha] = part
            row['chunks'].append(part_sha)
    now = int(time.time())
    index = dict(channel=LINUX_CHANNEL, revision=revision, issued=now, expires=now+120*86400, files=rows)
    signed = sign_index(encoded(index), certificate)
    if decode_index(signed, channel=LINUX_CHANNEL) != index:
        raise ValueError('Signed Linux update index does not match its payload.')
    output.mkdir(exist_ok=False)
    for pinned, raw in blobs.items():
        (output/f'starter-file-{pinned}.bin').write_bytes(raw)
    (output/LINUX_INDEX).write_bytes(signed)
    print(f'Linux update {revision} from signed Direct Starter r{current["revision"]}: {len(rows)} files.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for name in ('enable', 'feed'):
        command = commands.add_parser(name)
        command.add_argument('installer',type=Path)
        command.add_argument('output',type=Path)
        if name == 'feed':
            command.add_argument('--signed-snapshot',type=Path,required=True)
            command.add_argument('--revision',type=int,required=True)
            command.add_argument('--certificate',required=True,help='Current user signing certificate thumbprint')
    args = parser.parse_args()
    if args.action == 'enable':
        enable(args.installer,args.output)
    else:
        feed(args.installer,args.signed_snapshot,args.output,args.revision,args.certificate)


if __name__ == '__main__':
    main()
