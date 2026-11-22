"""Build and verify a guided Linux ZIP from a signed Direct feed and map cache."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256, file_digest
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

SOURCE = Path(__file__).resolve().parents[1]
MANIFEST = 'package-manifest.json'
INVITE = 'group-invitation.json'
INSTALLER = (
    'Install Clan Wars.sh', 'Start Community Starter.sh', 'install_clan_wars.py',
    'START HERE.txt', 'linux_launcher.py',
)


def metadata(name, raw):
    return {'path': name, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}


def check_paths(rows):
    seen = set()
    for name in rows:
        path = PurePosixPath(name)
        if (path.is_absolute() or path.as_posix() != name or not path.parts or '..' in path.parts
                or '\\' in name or ':' in name or name.casefold() in seen):
            raise ValueError(f'Unsafe or duplicate release path: {name}')
        seen.add(name.casefold())


def stage_feed(base, feed, cache):
    sys.path[:0] = [str(base), str(base/'lib')]
    import starter_update as updater

    signed = (feed/updater.INDEX).read_bytes()
    verified = updater.decode_index(signed, channel=updater.DIRECT_CHANNEL)

    def read(asset, limit):
        value = (feed/asset).read_bytes()
        if len(value) > limit:
            raise ValueError(f'Signed release asset exceeds its limit: {asset}')
        return value

    with updater.startup_lock(base) as state:
        updater.prepare(base, state, channel=updater.DIRECT_CHANNEL, fetch=read)
        updater.accept(state)
        assert not updater.prepare(base, state, channel=updater.DIRECT_CHANNEL, fetch=read)
    manifest = json.loads((base/MANIFEST).read_bytes())
    assert manifest['starter_update_revision'] == verified['revision']
    for name, pin in verified['files'].items():
        raw = (base/name).read_bytes()
        assert metadata(name, raw) == {'path':name, **pin}
    print(f'Signed client revision {verified["revision"]} verified.', flush=True)

    from direct_client import DirectClient, group_connection
    from map_sync import MapSync, overlay
    from map_sync_contract import map_catalog

    cache_paths = {}
    new_assets = feed/'downloaded-assets'
    new_assets.mkdir(exist_ok=True)
    with TemporaryDirectory() as device:
        client = DirectClient(group_connection(base, Path(device)/'device'))
        try:
            caps = client.capabilities()
            assert caps['publicCTF'] and not caps['publicOnly'] and caps['matchStartEnabled']
            assert client.resume() is None and isinstance(client.live_matches(), list)
            probe = MapSync(client, base, Path(device))
            probe.version = caps['mapFileSync']
            live = probe._inventory()
            rows, _, catalog, definitions = overlay(manifest, live)
            assert catalog.keys() == client.server_maps.keys()
            room = client.create('Clan Wars Linux Release Check')
            assert set(catalog) <= {item['id'] for item in room['availableMaps']}
            client.action('leave')
            archive_hashes = {(item['sha256'],item['bytes']) for item in manifest['files']
                              if item['path'].startswith('content/')}
            missing = {}
            for row in rows.values():
                name = row['sha256']+'.asset'
                cached = cache/name
                if cached.is_file():
                    cache_paths[row['path']] = cached
                elif (row['sha256'],row['bytes']) not in archive_hashes:
                    target = new_assets/name
                    cache_paths[row['path']] = target
                    if not target.is_file():
                        missing[target] = row
            if missing:
                print(f'Downloading {len(missing)} newly published map files '
                      f'({sum(item["bytes"] for item in missing.values())/1024**2:.0f} MiB).',flush=True)
                with ThreadPoolExecutor(max_workers=3) as workers:
                    list(workers.map(probe._download, missing.values(), missing.keys()))
        finally:
            if client.code:
                client.action('leave')
            client.close()

    bundled = dict(manifest, community_maps=live['community_maps'], map_definitions=definitions,
                   shared_content=live['shared_content'],
                   map_runtime={key:manifest['map_runtime'].get(key, []) for key in live['community_maps']})
    fixed = {row['path']:row for row in manifest['files'] if not row['path'].startswith('content/')}
    fixed.update(rows)
    bundled['files'] = list(fixed.values())
    assert map_catalog(bundled) == catalog
    print(f'{len(catalog)} live map fingerprints and lobby access verified.', flush=True)
    return verified, bundled, cache_paths, catalog


def write_member(zip_file, name, stream, row):
    info = ZipInfo(name)
    info.create_system = 3
    info.external_attr = ((0o100755 if name.endswith('.sh') else 0o100644) << 16)
    info.compress_type = ZIP_STORED if name.endswith('.tar.gz') else ZIP_DEFLATED
    info.file_size = row['bytes']
    digest = sha256()
    size = 0
    with zip_file.open(info, 'w') as output:
        while chunk := stream.read(1024**2):
            digest.update(chunk)
            size += len(chunk)
            output.write(chunk)
    if (size, digest.hexdigest()) != (row['bytes'], row['sha256']):
        raise ValueError(f'Input member failed verification: {name}')


def build(args, base):
    original = json.loads((base/MANIFEST).read_bytes())
    original_rows = {row['path']:row for row in original['files']}
    index, manifest, from_cache, catalog = stage_feed(base, args.feed, args.cache)
    build_id = f'Tribes-Rivals-Clan-Wars-Linux-Proton-r{index["revision"]}'
    runtime = args.feed/'Linux Python.tar.gz'
    python_pin = (args.feed/'Linux Python.sha256').read_bytes().strip()
    python_provenance = json.loads((args.feed/'python-provenance.json').read_bytes())
    assert python_provenance['digest'] == 'sha256:'+python_pin.decode('ascii')
    extras = {name:(SOURCE/name).read_bytes() for name in INSTALLER}
    extras.update({name:(base/name).read_bytes() for name in index['files']})
    extras['Linux Python.sha256'] = python_pin+b'\n'
    extras['README-Linux-Direct.txt'] = extras['START HERE.txt']
    support = json.loads((base/'linux-support.json').read_bytes())
    support.update(starter_revision=index['revision'], maps=len(catalog),
                   python_runtime=python_provenance, setup='START HERE.txt')
    extras['linux-support.json'] = json.dumps(support, indent=2).encode()+b'\n'
    release = json.loads((base/'DIRECT-RELEASE.json').read_bytes())
    release.update(build=build_id, starter_revision=index['revision'], map_catalog=catalog,
                   private_lobbies_verified=True, live_maps_verified=len(catalog))
    extras['DIRECT-RELEASE.json'] = json.dumps(release, indent=2).encode()+b'\n'

    rows = {row['path']:row for row in manifest['files']}
    rows.update({name:metadata(name, raw) for name,raw in extras.items()})
    rows[runtime.name] = {'path':runtime.name, 'bytes':runtime.stat().st_size, 'sha256':python_pin.decode()}
    manifest.update(build_id=build_id, revision_id=build_id, files=list(rows.values()))
    extras[MANIFEST] = json.dumps(manifest, indent=2).encode()+b'\n'
    extras[INVITE] = (base/INVITE).read_bytes()
    rows.update({name:metadata(name, extras[name]) for name in (MANIFEST, INVITE)})
    check_paths(rows)

    original_content = {(row['sha256'], row['bytes']):name for name,row in original_rows.items()
                        if name.startswith('content/')}
    from_base = defaultdict(list)
    for name,row in rows.items():
        if name in extras or name == runtime.name or name in from_cache:
            continue
        if name.startswith('content/'):
            key = (row['sha256'],row['bytes'])
            source = name if original_rows.get(name)==row else original_content.get(key)
        elif not name.startswith('content/'):
            source = name if original_rows.get(name)==row else None
        if source is None:
            raise ValueError(f'Missing exact bytes for {name}')
        from_base[source].append(name)

    output = args.output/(build_id+'.zip')
    partial = output.with_suffix('.zip.partial')
    if output.exists():
        raise FileExistsError(output)
    with ZipFile(partial, 'x', compression=ZIP_DEFLATED) as archive:
        for name in ('START HERE.txt','Install Clan Wars.sh'):
            write_member(archive,name,io.BytesIO(extras.pop(name)),rows[name])
        for name,raw in extras.items():
            write_member(archive,name,io.BytesIO(raw),rows[name])
        with runtime.open('rb') as stream:
            write_member(archive,runtime.name,stream,rows[runtime.name])
        with tarfile.open(args.archive,'r|gz') as source:
            prefix = args.archive.name.removesuffix('.tar.gz') + '/'
            for member in source:
                if not member.isfile() or not member.name.startswith(prefix):
                    raise ValueError('Unexpected source tar member')
                old_name = member.name.removeprefix(prefix)
                destinations = from_base.pop(old_name, ())
                if not destinations:
                    continue
                with source.extractfile(member) as stream:
                    if len(destinations) == 1:
                        name, = destinations
                        write_member(archive,name,stream,rows[name])
                    else:
                        raw = stream.read()
                        for name in destinations:
                            write_member(archive,name,io.BytesIO(raw),rows[name])
        if from_base:
            raise ValueError('Missing source records: '+repr(sorted(from_base)[:10]))
        for count,(name,path) in enumerate(from_cache.items(),1):
            with path.open('rb') as stream:
                write_member(archive,name,stream,rows[name])
            if count % 2000 == 0:
                print(f'Packed {count} cached assets and descriptors.',flush=True)
    with ZipFile(partial) as archive:
        assert sorted(archive.namelist()) == sorted(rows)
        for count,(name,row) in enumerate(rows.items(),1):
            assert archive.getinfo(name).file_size==row['bytes']
            with archive.open(name) as stream:
                assert file_digest(stream,'sha256').hexdigest()==row['sha256'], name
            if count % 2500 == 0:
                print(f'Read back {count} ZIP members.', flush=True)
    partial.rename(output)
    proof = {'revision':index['revision'], 'maps':len(catalog), 'verified_members':len(rows),
             'bytes':output.stat().st_size, 'archive':str(output), 'python':python_provenance,
             'map_catalog':catalog, 'private_lobby':True, 'live_matches':True}
    with output.open('rb') as stream:
        proof['sha256'] = file_digest(stream,'sha256').hexdigest()
    (args.feed/'release-proof.json').write_text(json.dumps(proof, indent=2), encoding='utf8')
    print(f'Verified {len(rows)} members in {output}',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('archive','base-stage','feed','cache','output'):
        parser.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix='clan-wars-release-',dir=args.feed) as folder:
        base = Path(folder)/'stage'
        shutil.copytree(args.base_stage,base,ignore=shutil.ignore_patterns('__pycache__','content','python'))
        build(args,base)


if __name__ == '__main__':
    main()
