"""Wrap the verified Linux Direct release in a shared Windows/Proton ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from build_linux_client import file_sha
from map_sync import overlay
from map_sync_contract import map_catalog
from community_maps import declared_definitions
from starter_update import DIRECT_CHANNEL, INDEX, decode_index, encoded
from tools.verify_player_release import safe_name
from tools.windows_starter_release import verify_live_revision


ROOT = Path(__file__).resolve().parent
CLIENT = 'Client Files/'
TITLE = 'Tribes Rivals: Clan Wars (community mod)'


def build(source, proof_path, output, *, feed=None, catalog=None, assets=None,
          map_objectives=None):
    proof = json.loads(proof_path.read_bytes())
    if source.stat().st_size != proof['bytes'] or file_sha(source) != proof['sha256']:
        raise ValueError('The original Direct Starter archive failed verification.')
    branding = ROOT/'branding'
    top = {
        'START HERE.txt': (branding/'START-HERE.txt').read_bytes(),
        'Start Clan Wars.bat': (branding/'Start Clan Wars.bat').read_text(encoding='ascii').replace('\n', '\r\n').encode('ascii'),
        'Clan Wars - Linux.sh': (branding/'clan-wars-linux.sh').read_text(encoding='utf8').encode('utf8'),
    }
    additions = {
        'clan_wars.py': (ROOT/'clan_wars.py').read_bytes(),
        'clan_wars_windows.pyw': (branding/'clan_wars_windows.pyw').read_bytes(),
        'branding/clan-wars.png': (branding/'clan-wars.png').read_bytes(),
        'branding/clan-wars.ico': (branding/'clan-wars.ico').read_bytes(),
    }
    if any(item is not None for item in (feed, catalog, assets)) and not all(
            item is not None for item in (feed, catalog, assets)):
        raise ValueError('Provide the signed feed, live catalog, and map assets together.')
    signed = decode_index((feed/INDEX).read_bytes(), channel=DIRECT_CHANNEL) if feed else None
    remote = json.loads(catalog.read_bytes()) if catalog else None
    replace = {name:(ROOT/name).read_bytes() for name in ('linux_launcher.py','linux_bootstrap.pyw')}
    removed = {'Start Community Starter.sh', 'README-Linux-Direct.txt'}
    expected = {}
    partial = output.with_suffix('.zip.partial')
    map_replacements = {}

    def write_bytes(zip_file, name, data):
        info = ZipInfo(name)
        info.compress_type = ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
        zip_file.writestr(info, data, compresslevel=1)
        expected[name] = (len(data), hashlib.sha256(data).hexdigest())

    prefix = proof['archive'].removesuffix('.tar.gz') + '/'
    with tarfile.open(source, 'r:gz') as metadata:
        with metadata.extractfile(prefix+'package-manifest.json') as payload:
            manifest = json.load(payload)
    if remote is not None:
        cooked, origins, _, definitions = overlay(manifest, remote)
        removed.update(row['path'] for row in manifest['files']
                       if row['path'].startswith('content/') and row['path'] not in cooked)
        map_replacements = {path:row for path,row in cooked.items() if origins[path] != path}
        manifest.update(community_maps=remote['community_maps'], map_definitions=definitions,
                        shared_content=remote['shared_content'],
                        map_runtime={name:manifest['map_runtime'].get(name, []) for name in remote['community_maps']},
                        files=[row for row in manifest['files'] if not row['path'].startswith('content/')]
                              + list(cooked.values()))
    if signed is not None:
        names = {row['path'] for row in manifest['files']}
        frozen = {path for paths in manifest['map_runtime'].values() for path in paths}
        if (signed['revision'] < manifest['starter_update_revision']
                or not set(manifest['starter_update_files']) <= signed['files'].keys() <= names
                or frozen & signed['files'].keys()):
            raise ValueError('The signed feed is incompatible with the source archive.')
        for name, row in signed['files'].items():
            data = (feed/('starter-file-'+row['sha256']+'.bin')).read_bytes()
            if (len(data), hashlib.sha256(data).hexdigest()) != (row['bytes'],row['sha256']):
                raise ValueError(f'Signed Starter file failed verification: {name}')
            replace[name] = data
        manifest.update(starter_update_revision=signed['revision'],
                        starter_update_files=sorted(signed['files']))
    if map_objectives is not None:
        inventory = json.loads((map_objectives / 'package-manifest.json').read_bytes())
        rows = {row['path']: row for row in inventory['files']}
        for definition in declared_definitions(manifest).values():
            name = f'lua/{definition.id}/objectives.lua'
            row = rows.get(name)
            if definition.native or row is None:
                continue
            source_path = map_objectives / name
            if source_path.resolve(strict=True) != source_path or not 0 < row['bytes'] <= 256 * 1024:
                raise ValueError(f'Invalid packaged objectives file: {name}')
            with source_path.open('rb') as payload:
                data = payload.read(row['bytes'] + 1)
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError(f'Packaged map objectives failed verification: {name}')
            replace[name] = data
        replace['lua/weather.lua'] = (ROOT / 'lua/weather.lua').read_bytes()
        # Older hosts fingerprint the original module as shared map runtime.
        # Ship the stub once the selected host catalog no longer pins that file.
        if not any('lua/snowblind_weather.lua' in names for names in manifest['map_runtime'].values()):
            replace['lua/snowblind_weather.lua'] = (ROOT / 'lua/snowblind_weather.lua').read_bytes()
        replace['client.py'] = (ROOT / 'client_entry.py').read_bytes()
    with tarfile.open(source, 'r|gz') as original, ZipFile(partial, 'x', ZIP_DEFLATED, compresslevel=1) as package:
        for name, data in top.items():
            write_bytes(package, name, data)
        seen = set()
        for entry in original:
            if not entry.isfile() or not entry.name.startswith(prefix):
                raise ValueError('Unexpected source archive member.')
            name = entry.name.removeprefix(prefix)
            safe_name(name)
            if name.casefold() in seen or name in additions:
                raise ValueError('Unexpected duplicate or branding file.')
            seen.add(name.casefold())
            if name in removed or name in replace or name in map_replacements or name == 'package-manifest.json':
                continue
            with original.extractfile(entry) as payload, package.open(CLIENT+name, 'w', force_zip64=True) as member:
                if name == 'group-invitation.json':
                    data = payload.read()
                    member.write(data)
                    expected[CLIENT+name] = (len(data), hashlib.sha256(data).hexdigest())
                else:
                    shutil.copyfileobj(payload, member, 1024*1024)
            if len(seen) % 1500 == 0:
                print(f'Packed {len(seen)}/{proof["verified_members"]} source files', flush=True)
        if len(seen) != proof['verified_members']:
            raise ValueError('Unexpected source inventory.')
        original_catalog = map_catalog(manifest)
        rows = {row['path']: row for row in manifest['files'] if row['path'] not in removed | replace.keys()}
        for name, row in map_replacements.items():
            path = assets/(row['sha256']+'.asset')
            with path.open('rb') as payload, package.open(CLIENT+name,'w',force_zip64=True) as member:
                shutil.copyfileobj(payload,member,1024*1024)
        for name, data in (replace | additions).items():
            write_bytes(package, CLIENT+name, data)
            size, sha = expected[CLIENT+name]
            rows[name] = {'path':name,'bytes':size,'sha256':sha}
        manifest.update(files=list(rows.values()), display_name=TITLE)
        if map_catalog(manifest) != original_catalog or (remote is not None and original_catalog != remote['maps']):
            raise ValueError('The wrapped package changed its map fingerprints.')
        write_bytes(package, CLIENT+'package-manifest.json', encoded(manifest))
        expected.update({CLIENT+name:(row['bytes'],row['sha256']) for name,row in rows.items()})
    print('Checking ZIP integrity and file hashes', flush=True)
    with ZipFile(partial) as package:
        names = package.namelist()
        if set(names) != expected.keys() or len(names) != len(set(names)):
            raise ValueError('Final ZIP inventory differs.')
        for name in names:
            info = package.getinfo(name)
            with package.open(info) as payload:
                digest = hashlib.file_digest(payload,'sha256').hexdigest()
            if name in expected and expected[name] != (info.file_size,digest):
                raise ValueError(f'Failed archive verification: {name}')
    try:
        with ZipFile(partial) as package:
            verify_live_revision(package)
    except Exception:
        partial.unlink()
        raise
    partial.rename(output)
    return {'archive':output.name,'bytes':output.stat().st_size,'sha256':file_sha(output),
            'starter_revision':manifest['starter_update_revision'],'maps':len(original_catalog),
            'verified_members':len(names)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','source-proof','output','proof'):
        parser.add_argument('--'+name, required=True, type=Path)
    for name in ('feed','catalog','assets','map-objectives'):
        parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    result = build(args.source,args.source_proof,args.output,
                   feed=args.feed,catalog=args.catalog,assets=args.assets,
                   map_objectives=args.map_objectives.resolve(strict=True) if args.map_objectives else None)
    with args.proof.open('xb') as stream:
        stream.write(encoded(result))
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
