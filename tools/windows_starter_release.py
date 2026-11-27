"""Reissue a full Windows Clan Wars ZIP with the live signed Starter revision."""

import argparse
from copy import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from starter_update import DIRECT_CHANNEL, INDEX, MAX_INDEX, decode_index, encoded, fetcher, sha
from tools.verify_player_release import safe_name


CLIENT = 'Client Files/'
MANIFEST = CLIENT + 'package-manifest.json'
INVITATION = CLIENT + 'group-invitation.json'
OPENER = 'Start Clan Wars.bat'


def read_bounded(package, name, limit):
    with package.open(name) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'Oversized ZIP member: {name}')
    return data


def manifest_for(package):
    files = set()
    for member in package.infolist():
        name = member.filename.removesuffix('/')
        safe_name(name)
        if name.casefold() in files:
            raise ValueError(f'Duplicate ZIP member: {name}')
        files.add(name.casefold())
    required = {OPENER, INVITATION, MANIFEST, CLIENT + 'python/pythonw.exe',
                CLIENT + 'clan_wars_windows.pyw'}
    if not required <= set(package.namelist()) or any(
            package.getinfo(name).is_dir() for name in required):
        raise ValueError('Expected the full Windows Direct Starter ZIP with its top-level BAT.')
    manifest = json.loads(read_bounded(package, MANIFEST, 16 * 1024**2))
    if 'direct_host_contract' not in manifest or type(manifest.get('starter_update_revision')) is not int:
        raise ValueError('Expected a versioned Direct Starter manifest.')
    return manifest


def live_fetch(package):
    invitation = read_bounded(package, INVITATION, 16384)

    def fetch(name, bound):
        with TemporaryDirectory(prefix='clan-wars-feed-') as directory:
            root = Path(directory).resolve()
            (root / 'group-invitation.json').write_bytes(invitation)
            # Release packaging downloads independently of the launcher's
            # single startup deadline. Each request keeps the normal TLS checks.
            return fetcher(channel=DIRECT_CHANNEL, root=root)(name, bound)

    return fetch


def live_index(fetch):
    return decode_index(fetch(INDEX, MAX_INDEX), channel=DIRECT_CHANNEL)


def verify_index(package, manifest, index):
    revision = index['revision']
    if manifest['starter_update_revision'] != revision:
        raise ValueError(f'The ZIP bundles r{manifest["starter_update_revision"]}; the live feed is r{revision}.')
    files = index['files']
    if set(manifest['starter_update_files']) != files.keys():
        raise ValueError('The ZIP and signed feed manage different Starter files.')
    inventory = {row['path']: row for row in manifest['files']}
    for name, expected in files.items():
        data = read_bounded(package, CLIENT + name, expected['bytes'])
        row = inventory.get(name, {})
        actual = {'bytes': len(data), 'sha256': sha(data)}
        if actual != expected or any(row.get(key) != value for key, value in expected.items()):
            raise ValueError(f'Starter file does not match the live signed feed: {name}')
    return revision


def verify_live_revision(package):
    manifest = manifest_for(package)
    return verify_index(package, manifest, live_index(live_fetch(package)))


def archive_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_archive(path, expected_sha=None):
    if expected_sha is not None and archive_sha(path) != expected_sha:
        raise ValueError('Windows ZIP SHA-256 differs from the qualified release.')
    with ZipFile(path) as package:
        return verify_live_revision(package)


def reissue(base, expected_sha, output):
    base, output = Path(base), Path(output)
    if output.suffix.lower() != '.zip' or output.exists():
        raise ValueError('Choose a new .zip filename.')
    if archive_sha(base) != expected_sha:
        raise ValueError('Base Windows ZIP SHA256 mismatch.')

    with TemporaryDirectory(prefix='clan-wars-zip-', dir=output.parent) as directory:
        partial = Path(directory) / output.name
        with ZipFile(base) as original:
            manifest = manifest_for(original)
            fetch = live_fetch(original)
            index = live_index(fetch)
            files = index['files']
            inventory = {row['path']: row for row in manifest['files']}
            frozen = {name for names in manifest['map_runtime'].values() for name in names}
            if (index['revision'] < manifest['starter_update_revision']
                    or not set(manifest['starter_update_files']) <= files.keys() <= inventory.keys()
                    or files.keys() & frozen):
                raise ValueError('The live signed feed is incompatible with the base Windows ZIP.')

            replacements = {}
            for name, row in files.items():
                data = fetch(f'starter-file-{row["sha256"]}.bin', row['bytes'])
                if len(data) != row['bytes'] or sha(data) != row['sha256']:
                    raise ValueError(f'Signed Starter file failed verification: {name}')
                inventory[name].update(row)
                replacements[CLIENT + name] = data
            manifest.update(starter_update_revision=index['revision'], starter_update_files=sorted(files))
            replacements[MANIFEST] = encoded(manifest)

            with ZipFile(partial, 'x', ZIP_DEFLATED, compresslevel=1) as result:
                for info in original.infolist():
                    name = info.filename
                    member = copy(info)
                    member.compress_type = ZIP_DEFLATED
                    member.compress_level = 1
                    if name in replacements:
                        result.writestr(member, replacements[name])
                    elif info.is_dir():
                        result.mkdir(member)
                    else:
                        with original.open(info) as source, result.open(member, 'w', force_zip64=True) as target:
                            shutil.copyfileobj(source, target, 1024**2)

        with ZipFile(partial) as package:
            if corrupt := package.testzip():
                raise ValueError(f'Corrupted rebuilt ZIP member: {corrupt}')
            # A new feed can go live while the multi-gigabyte ZIP is packing.
            revision = verify_index(package, manifest_for(package), live_index(fetch))
        partial.rename(output)
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build', help='Apply the live signed feed to a pinned full Windows ZIP.')
    build.add_argument('--base', type=Path, required=True)
    build.add_argument('--base-sha256', required=True)
    build.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser('verify', help='Check a trusted ZIP against the current live signed feed.')
    verify.add_argument('archive', type=Path)
    verify.add_argument('--sha256', help='Require the exact SHA-256 of the qualified archive.')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            revision = reissue(args.base, args.base_sha256, args.output)
            print(f'Built and verified Windows Starter r{revision}: {args.output}')
        else:
            revision = verify_archive(args.archive, args.sha256)
            print(f'Windows ZIP matches the live signed Starter r{revision} feed.')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
