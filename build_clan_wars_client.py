"""Wrap the verified Linux Direct release in a shared Windows/Proton ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from build_linux_client import file_sha
from map_sync_contract import map_catalog
from starter_update import encoded
from tools.verify_player_release import safe_name


ROOT = Path(__file__).resolve().parent
CLIENT = 'Client Files/'
TITLE = 'Tribes Rivals: Clan Wars (community mod)'


def build(source, proof_path, windows_launcher, output):
    proof = json.loads(proof_path.read_bytes())
    if source.stat().st_size != proof['bytes'] or file_sha(source) != proof['sha256']:
        raise ValueError('The original Direct Starter archive failed verification.')
    branding = ROOT/'branding'
    top = {
        'START HERE.txt': (branding/'START-HERE.txt').read_bytes(),
        'Clan Wars - Windows.exe': windows_launcher.read_bytes(),
        'Clan Wars - Linux.sh': (branding/'clan-wars-linux.sh').read_text(encoding='utf8').encode('utf8'),
    }
    additions = {
        'clan_wars.py': (ROOT/'clan_wars.py').read_bytes(),
        'clan_wars_windows.pyw': (branding/'clan_wars_windows.pyw').read_bytes(),
        'branding/clan-wars.png': (branding/'clan-wars.png').read_bytes(),
        'branding/clan-wars.ico': (branding/'clan-wars.ico').read_bytes(),
    }
    replace = {name:(ROOT/name).read_bytes() for name in ('linux_launcher.py','linux_bootstrap.pyw')}
    removed = {'Start Community Starter.sh', 'README-Linux-Direct.txt'}
    expected = {}
    partial = output.with_suffix('.zip.partial')
    manifest = None

    def write_bytes(zip_file, name, data):
        info = ZipInfo(name)
        info.compress_type = ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
        zip_file.writestr(info, data, compresslevel=1)
        expected[name] = (len(data), hashlib.sha256(data).hexdigest())

    prefix = proof['archive'].removesuffix('.tar.gz') + '/'
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
            if name in removed or name in replace:
                continue
            with original.extractfile(entry) as payload:
                if name == 'package-manifest.json':
                    manifest = json.load(payload)
                else:
                    with package.open(CLIENT+name, 'w', force_zip64=True) as member:
                        if name == 'group-invitation.json':
                            data = payload.read()
                            member.write(data)
                            expected[CLIENT+name] = (len(data), hashlib.sha256(data).hexdigest())
                        else:
                            shutil.copyfileobj(payload, member, 1024*1024)
            if len(seen) % 1500 == 0:
                print(f'Packed {len(seen)}/{proof["verified_members"]} source files', flush=True)
        if manifest is None or len(seen) != proof['verified_members']:
            raise ValueError('Unexpected source inventory.')
        original_catalog = map_catalog(manifest)
        rows = {row['path']: row for row in manifest['files'] if row['path'] not in removed | replace.keys()}
        for name, data in (replace | additions).items():
            write_bytes(package, CLIENT+name, data)
            size, sha = expected[CLIENT+name]
            rows[name] = {'path':name,'bytes':size,'sha256':sha}
        manifest.update(files=list(rows.values()), display_name=TITLE)
        if map_catalog(manifest) != original_catalog or len(original_catalog) != proof['maps']:
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
    partial.rename(output)
    return {'archive':output.name,'bytes':output.stat().st_size,'sha256':file_sha(output),
            'starter_revision':manifest['starter_update_revision'],'maps':len(original_catalog),
            'verified_members':len(names)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','source-proof','launcher','output','proof'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    result = build(args.source,args.source_proof,args.launcher,args.output)
    with args.proof.open('xb') as stream:
        stream.write(encoded(result))
    print(json.dumps(result),flush=True)


if __name__ == '__main__':
    main()
