"""Install the verified payload of the self-extracting Clan Wars release."""
import argparse
from base64 import b64decode
import fcntl
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

PREVIEW = None


def verify_payload(launcher, offset, expected):
    digest = sha256()
    with launcher.open('rb') as stream:
        stream.seek(offset)
        while chunk := stream.read(1024**2):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError('The download is incomplete or damaged. Download the installer again.')


def members(archive):
    paths = {}
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if (member.is_dir() or not path.parts or path.is_absolute() or '..' in path.parts
                or path.as_posix() != member.filename or '\\' in member.filename
                or member.filename.casefold() in paths):
            raise ValueError(f'Unexpected installer entry: {member.filename}')
        paths[member.filename.casefold()] = member
    manifest = json.loads(archive.read('package-manifest.json'))
    expected = {record['path'] for record in manifest['files']} | {
        'package-manifest.json', 'group-invitation.json',
    }
    if {entry.filename for entry in paths.values()} != expected:
        raise ValueError('The installer contents differ from the client inventory.')
    return tuple(paths.values()), manifest


def install(archive, entries, destination, expected):
    destination.parent.mkdir(parents=True, exist_ok=True)
    lockfile = destination.parent/(destination.name+'.install-lock')
    fd = os.open(lockfile, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists() or destination.is_symlink():
            stamp = destination/'.clan-wars-installer-sha256'
            if (destination.is_symlink() or not stamp.is_file()
                    or stamp.read_text().strip() != expected
                    or not (destination/entrypoint()).is_file()):
                raise ValueError(f'Choose a different empty installation path. {destination} already exists.')
            print(f'Clan Wars is already installed at {destination}', flush=True)
            return
        required = sum(entry.file_size for entry in entries)
        if shutil.disk_usage(destination.parent).free < required + 256 * 1024**2:
            raise ValueError(f'Free up at least {(required + 256 * 1024**2)/1024**3:.1f} GiB '
                             f'on the drive that contains {destination.parent}.')
        with TemporaryDirectory(prefix='.clan-wars-', dir=destination.parent) as temporary:
            root = Path(temporary)/'client'
            root.mkdir()
            final = len(entries)
            for number, entry in enumerate(entries, 1):
                target = root/entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024**2)
                if entry.filename in ('Install Clan Wars.sh', 'Start Community Starter.sh'):
                    target.chmod(0o755)
                if number % 2000 == 0 or number == final:
                    print(f'Installing Clan Wars ({number:,}/{final:,} files)', flush=True)
            if PREVIEW is not None:
                install_preview(root)
            (root/'.clan-wars-installer-sha256').write_text(expected+'\n', encoding='ascii')
            root.rename(destination)
    print(f'Installed Clan Wars in {destination}', flush=True)


def entrypoint():
    return 'Start Clan Wars Ubuntu.sh' if PREVIEW is not None else 'Install Clan Wars.sh'


def install_preview(root):
    manifest_path = root/'package-manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    rows = {row['path']:row for row in manifest['files']}
    for name, encoded in PREVIEW.items():
        target = root/name
        raw = b64decode(encoded,validate=True)
        target.write_bytes(raw)
        if name.endswith('.sh'):
            target.chmod(0o755)
        rows[name] = {'path':name,'bytes':len(raw),'sha256':sha256(raw).hexdigest()}
    manifest.update(files=list(rows.values()), build_id='ClanWarsUbuntuNativePreview1',
                    revision_id='ClanWarsUbuntuNativePreview1')
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')


def main():
    launcher, offset, digest, *args = sys.argv[1:]
    parser = argparse.ArgumentParser(description='Install Clan Wars for Linux or Steam Deck.')
    parser.add_argument('--destination', type=Path, help='Install to this directory')
    parser.add_argument('--install-only', action='store_true', help='Skip opening Steam setup')
    parser.add_argument('--verify', action='store_true', help='Verify the installer without installing')
    options = parser.parse_args(args)
    launcher = Path(launcher)
    print('Checking the Clan Wars installerâ€¦', flush=True)
    verify_payload(launcher, int(offset), digest)
    installer_id = digest if PREVIEW is None else sha256((digest+json.dumps(PREVIEW,sort_keys=True)).encode()).hexdigest()
    with ZipFile(launcher) as archive:
        entries, manifest = members(archive)
        revision = manifest['starter_update_revision']
        if options.verify:
            print(f'Clan Wars r{revision} verified with {len(manifest["community_maps"])} maps.')
            return 0
        title = 'Clan Wars Ubuntu Preview' if PREVIEW is not None else f'Clan Wars Linux r{revision}'
        destination = options.destination or Path.home()/'Games'/title
        destination = destination.expanduser().absolute()
        install(archive, entries, destination, installer_id)
    if options.install_only:
        return 0
    return subprocess.call(['/bin/sh', str(destination/entrypoint())])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as problem:
        print(f'Clan Wars installer: {problem}', file=sys.stderr)
        sys.exit(1)
