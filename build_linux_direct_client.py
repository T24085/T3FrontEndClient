"""Build a Steam Proton archive from a pinned public Direct Starter ZIP."""
import argparse
import io
import json
from pathlib import Path
import tarfile
from zipfile import ZipFile

from build_linux_client import EXECUTABLE, MANIFEST, PLATFORM, ROOT, file_sha, verify_archive
from direct_update_contract import ROUTE
from map_sync import overlay
from map_sync_contract import CATALOG_VERSION, map_catalog
from starter_update import DIRECT_CHANNEL, INDEX, decode_index, encoded, sha
from tools.build_player_release import git
from tools.verify_player_release import safe_name


INVITATION = 'group-invitation.json'
RELEASE = 'DIRECT-RELEASE.json'
LAUNCH_FILES = (EXECUTABLE, 'linux_launcher.py', 'linux_bootstrap.pyw', 'README-Linux-Direct.txt')
WINDOWS_SHORTCUTS = {'Start Direct Starter.bat', 'Change Host Invitation.bat', 'direct_starter.pyw',
                     'change_invitation.pyw', 'READ THIS FIRST.txt'}


def build(source, source_sha, catalog_path, assets, feed, archive):
    if archive.exists() or not archive.name.endswith('.tar.gz'):
        raise ValueError('Choose a fresh .tar.gz path.')
    if file_sha(source) != source_sha:
        raise ValueError('Windows source archive digest mismatch.')
    index = decode_index((feed / INDEX).read_bytes(), channel=DIRECT_CHANNEL)
    remote = json.loads(catalog_path.read_bytes())
    if remote['format'] != CATALOG_VERSION:
        raise ValueError('Expected the current Direct Starter map catalog.')
    prefix = archive.name.removesuffix('.tar.gz') + '/'
    partial = archive.with_name(archive.name + '.partial')
    with ZipFile(source) as base:
        manifest_path, = (name for name in base.namelist() if name.endswith('/' + MANIFEST))
        windows_root = manifest_path.removesuffix(MANIFEST)
        if not windows_root.endswith('/') or windows_root.count('/') != 1:
            raise ValueError('Expected one Windows package root.')
        raw = base.read(manifest_path)
        manifest = json.loads(raw)
        members = {row['path']:row for row in manifest['files']}
        names = [name for name in base.namelist() if not name.endswith('/')]
        extras = {INVITATION, RELEASE, MANIFEST}
        if (len(set(name.casefold() for name in names)) != len(names)
                or len(members) != len(manifest['files'])
                or set(names) != {windows_root + name for name in members.keys() | extras}):
            raise ValueError('Windows ZIP differs from its declared player inventory.')
        for name in members.keys() | extras:
            safe_name(name)
        release = json.loads(base.read(windows_root + RELEASE))
        if (not manifest.get('direct_host_contract') or release.get('role') != 'player'
                or release.get('group_enrollment') != 1 or manifest.get('capabilities') != ['join-only']):
            raise ValueError('Expected an enrolled Direct Starter player archive.')
        if index['revision'] < manifest.get('starter_update_revision', 0):
            raise ValueError('Signed update is older than the ZIP.')
        rows, origins, catalog, custom = overlay(manifest, remote)
        members = {name: row for name, row in members.items()
                   if not name.startswith('content/') and name not in WINDOWS_SHORTCUTS}
        members.update(rows)
        frozen = {name for files in manifest['map_runtime'].values() for name in files}
        if (not index['files'].keys() <= members.keys() or index['files'].keys() & frozen
                or not set(manifest.get('starter_update_files', [])) <= index['files'].keys()):
            raise ValueError('Signed feed is incompatible with this Windows base.')
        replacements = {name: (ROOT / name).read_bytes() for name in LAUNCH_FILES}
        for name, row in index['files'].items():
            payload = (feed / ('starter-file-' + row['sha256'] + '.bin')).read_bytes()
            if (len(payload), sha(payload)) != (row['bytes'], row['sha256']):
                raise ValueError(f'Signed Starter payload mismatch: {name}')
            replacements[name] = payload
        release.update(build=prefix[:-1], platform=PLATFORM, map_catalog=catalog)
        invitation = base.read(windows_root + INVITATION)
        replacements[RELEASE] = encoded(release)
        replacements['linux-support.json'] = encoded({
            'platform': PLATFORM, 'windows_archive_sha256': source_sha,
            'frontend_source_commit': git(ROOT, 'rev-parse', 'HEAD'), 'starter_revision': index['revision'],
            'maps': len(catalog), 'update_route': ROUTE, 'gameplay_qualified': False,
        })
        for name, data in replacements.items():
            members[name] = {'path': name, 'bytes': len(data), 'sha256': sha(data)}
        manifest.update(platform=PLATFORM, build_id=prefix[:-1], release_id=prefix[:-1],
                        starter_update_revision=index['revision'], starter_update_files=sorted(index['files']),
                        map_runtime={name: manifest['map_runtime'].get(name, []) for name in catalog},
                        community_maps=remote['community_maps'], map_definitions=custom,
                        shared_content=remote['shared_content'], files=list(members.values()))
        if map_catalog(manifest) != catalog:
            raise ValueError('Linux package changed map fingerprints.')
        replacements[MANIFEST] = encoded(manifest)
        replacements[INVITATION] = invitation
        expected = dict(members)
        for name in (MANIFEST, INVITATION):
            expected[name] = {'bytes': len(replacements[name]), 'sha256': sha(replacements[name])}
        with tarfile.open(partial, 'x:gz', compresslevel=3) as output:
            for count, (name, row) in enumerate(sorted(expected.items()), 1):
                entry = tarfile.TarInfo(prefix + name)
                entry.mode = 0o755 if name == EXECUTABLE else 0o644
                entry.size = row['bytes']
                if name in replacements:
                    payload = io.BytesIO(replacements[name])
                elif name in origins and origins[name] is None:
                    payload = (assets / (row['sha256'] + '.asset')).open('rb')
                else:
                    payload = base.open(windows_root + origins.get(name, name))
                with payload:
                    output.addfile(entry, payload)
                if count % 1000 == 0:
                    print(f'Packed {count}/{len(expected)} members', flush=True)
    verify_archive(partial, prefix, expected)
    partial.rename(archive)
    return {'archive': archive.name, 'bytes': archive.stat().st_size, 'sha256': file_sha(archive),
            'revision': index['revision'], 'maps': len(catalog), 'verified_members': len(expected)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'catalog', 'assets', 'feed', 'archive', 'proof'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    result = build(args.source, args.source_sha256, args.catalog, args.assets, args.feed, args.archive)
    with args.proof.open('xb') as stream:
        stream.write(encoded(result))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
