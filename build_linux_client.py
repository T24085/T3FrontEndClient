"""Build the Linux/Proton distribution from an exact published Windows r12 ZIP."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from zipfile import ZipFile

from map_sync import overlay
from map_sync_contract import CATALOG_VERSION
from tools.build_player_release import encoded, git, sha
from tools.verify_player_release import map_catalog, safe_name

ROOT = Path(__file__).resolve().parent
WINDOWS_ROOT = 'TRIBES3-Community-Starter/'
PLATFORM = 'linux-x86_64-through-steam-proton'
SOURCE_FILES = (
    'community_starter.pyw', 'starter_update.py', 'linux_bootstrap.pyw',
    'linux_launcher.py', 'Start Community Starter.sh', 'README-Linux.txt',
)
WINDOWS_ONLY = {'Start Community Starter.bat', 'Start Community Starter.vbs', 'README-FIRST.txt'}
EXECUTABLE = 'Start Community Starter.sh'
MANIFEST = 'package-manifest.json'


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_archive(archive, prefix, expected):
    remaining = dict(expected)
    with tarfile.open(archive, 'r|gz') as stream:
        for info in stream:
            if not info.isfile() or not info.name.startswith(prefix):
                raise ValueError('Non-regular or out-of-package tar member.')
            name = info.name[len(prefix):]
            row = remaining.pop(name)
            with stream.extractfile(info) as member:
                if info.size != row['bytes'] or hashlib.file_digest(member, 'sha256').hexdigest() != row['sha256']:
                    raise ValueError('Linux archive member failed verification: ' + name)
            if info.mode != (0o755 if name == EXECUTABLE else 0o644):
                raise ValueError('Unexpected tar member permissions: ' + name)
    if remaining:
        raise ValueError('Incomplete Linux archive.')


def build(source, source_sha, archive, proof, server_catalog, map_assets):
    source, archive, proof = (Path(p).resolve() for p in (source, archive, proof))
    if any(p.exists() or ROOT in p.parents for p in (archive, proof)):
        raise ValueError('Choose fresh output paths outside the source checkout.')
    if not archive.name.endswith('.tar.gz'):
        raise ValueError('Expected a .tar.gz output.')
    if git(ROOT, 'status', '--porcelain'):
        raise ValueError('Build from a clean source checkout.')
    commit = git(ROOT, 'rev-parse', 'HEAD')
    print('Checking the published Windows r12 archive...', flush=True)
    if file_sha(source) != source_sha:
        raise ValueError('Published Windows archive digest mismatch.')
    prefix = archive.name.removesuffix('.tar.gz') + '/'
    with ZipFile(source) as base:
        manifest_raw = base.read(WINDOWS_ROOT + MANIFEST)
        manifest = json.loads(manifest_raw)
        old_release = manifest['release_id']
        if old_release != 'Windows-20261108-r12' or manifest['capabilities'] != ['join-only']:
            raise ValueError('Expected the published join-only Windows r12 client.')
        rows = {r['path']: r for r in manifest['files']}
        names = [n for n in base.namelist() if not n.endswith('/')]
        if (len(rows) != len(manifest['files']) or len({n.casefold() for n in names}) != len(names)
                or set(names) != {WINDOWS_ROOT + n for n in (*rows, MANIFEST)}):
            raise ValueError('Windows ZIP differs from its declared inventory.')
        for name in rows:
            safe_name(name)
        baseline_catalog = map_catalog(manifest)
        release = json.loads(base.read(WINDOWS_ROOT + 'RELEASE-INFO.json'))
        provenance = json.loads(base.read(WINDOWS_ROOT + 'SOURCE-INFO.json'))
        if release['verified_map_catalog'] != baseline_catalog:
            raise ValueError('Windows map catalog differs from its inventory.')
        remote = json.loads(Path(server_catalog).read_bytes())
        if remote['format'] != CATALOG_VERSION:
            raise ValueError('Expected the current server map catalog.')
        cooked, origins, catalog, custom = overlay(manifest, remote)
        rows = {name: row for name, row in rows.items() if not name.startswith('content/')}
        rows.update(cooked)
        manifest.update(shared_content=remote['shared_content'], community_maps=remote['community_maps'],
                        map_definitions=custom,
                        map_runtime={name: manifest['map_runtime'].get(name, []) for name in catalog})
        changed_maps = sorted(name for name in catalog if catalog[name] != baseline_catalog.get(name))
        assets = Path(map_assets)
        replacements = {name: (ROOT / name).read_bytes() for name in SOURCE_FILES}
        release_id = old_release.replace('Windows-', 'Linux-Proton-')
        support = {'platform': PLATFORM, 'source_archive_sha256': source_sha,
                   'source_manifest_sha256': sha(manifest_raw), 'parent_release': old_release,
                   'frontend_source_commit': commit, 'map_count': len(catalog),
                   'runtime_qualification': 'Steam/Proton multiplayer and Steam Deck Gaming Mode require a player test.',
                   'server_included': False, 'setup': 'README-Linux.txt'}
        source_commits = {**manifest['source_commits'], 'frontend': commit}
        source_members = {**provenance['source_members'],
                          **{name: {'source': name, 'sha256': sha(raw)} for name, raw in replacements.items()}}
        provenance.update(source_commits=source_commits, source_members=source_members,
                          base_archive_sha256=source_sha)
        release.update(release=release_id, parent_release=old_release, platform=PLATFORM,
                       source_commits=source_commits, verified_map_catalog=catalog, maps=list(catalog),
                       changed_map_ids=changed_maps)
        replacements.update({'linux-support.json': encoded(support), 'RELEASE-INFO.json': encoded(release),
                             'SOURCE-INFO.json': encoded(provenance)})
        for name in WINDOWS_ONLY:
            del rows[name]
        for name, raw in replacements.items():
            rows[name] = {'path': name, 'bytes': len(raw), 'sha256': sha(raw)}
        manifest.update(build_id=prefix[:-1], revision_id=release_id, release_id=release_id,
                        platform=PLATFORM, source_commits=source_commits, files=list(rows.values()))
        if map_catalog(manifest) != catalog:
            raise ValueError('The Linux adapter changed map fingerprints.')
        replacements[MANIFEST] = encoded(manifest)
        expected = {**rows, MANIFEST: {'bytes': len(replacements[MANIFEST]), 'sha256': sha(replacements[MANIFEST])}}
        archive.parent.mkdir(parents=True, exist_ok=True)
        print('Packing the Linux r12 archive...', flush=True)
        with tarfile.open(archive, 'x:gz', compresslevel=3) as output:
            for count, (name, row) in enumerate(sorted(expected.items()), 1):
                entry = tarfile.TarInfo(prefix + name)
                entry.size = row['bytes']
                entry.mode = 0o755 if name == EXECUTABLE else 0o644
                if name in replacements:
                    payload = io.BytesIO(replacements[name])
                elif name in origins and origins[name] is None:
                    payload = (assets / (row['sha256'] + '.asset')).open('rb')
                else:
                    payload = base.open(WINDOWS_ROOT + origins.get(name, name))
                with payload:
                    output.addfile(entry, payload)
                if count % 1000 == 0:
                    print(f'Packed {count}/{len(expected)} members', flush=True)
    if archive.stat().st_size >= 2 * 1024**3:
        raise ValueError('Release asset exceeds the GitHub size limit.')
    print('Verifying every Linux archive member...', flush=True)
    verify_archive(archive, prefix, expected)
    report = {'archive': archive.name, 'archive_bytes': archive.stat().st_size, 'archive_sha256': file_sha(archive),
              'verified_members': len(expected), 'map_count': len(catalog), 'verified_map_catalog': catalog,
              'source_commits': source_commits, 'windows_archive_sha256': source_sha,
              'all_archive_members_sha256_verified': True, 'updated_maps': changed_maps}
    with proof.open('xb') as output:
        output.write(encoded(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--server-catalog', type=Path, required=True)
    parser.add_argument('--map-assets', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source, args.source_sha256, args.archive, args.proof, args.server_catalog, args.map_assets)
    print(json.dumps({k: v for k, v in result.items() if k != 'verified_map_catalog'}), flush=True)


if __name__ == '__main__':
    main()
