"""Freeze a join-only Proton candidate from a pinned client; never overwrite a release."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import time

ROOT = Path(__file__).resolve().parent
ADDITIONS = ('linux_launcher.py', 'linux_bootstrap.pyw', 'Start Community Starter.sh', 'README-Linux.txt')
FORBIDDEN = {'server.py', 'host.py', 'playtest.py', 'run_lobby_service.py', 'private-config.json',
             'lobby-server-defaults.json', 'community-lobby.key', 'lua/network.lua'}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(source, expected_source_sha256, output, archive):
    source = Path(source).resolve(strict=True)
    output, archive = Path(output).absolute(), Path(archive).absolute()
    if output.exists() or archive.exists():
        raise ValueError('Choose a fresh output directory and archive; previous releases are retained.')
    if sha(source/'package-manifest.json') != expected_source_sha256:
        raise ValueError('Selected client manifest changed.')
    manifest = json.loads((source/'package-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('capabilities') != ['join-only']:
        raise ValueError('A verified join-only source is required.')
    seen = set()
    for member in manifest['files']:
        name = member['path']
        rel = PurePosixPath(name)
        if (not rel.parts or rel.is_absolute() or rel.as_posix() != name or '..' in rel.parts
                or ':' in name or '\\' in name or name.casefold() in seen
                or name in FORBIDDEN or name.lower().endswith(('.pak', 'tribesrivals.exe'))):
            raise ValueError('Unsafe or hosting/original-game member: '+name)
        seen.add(name.casefold())
        path = (source/name).resolve(strict=True)
        if ((source/name).is_symlink() or (source/name).is_junction() or source not in path.parents
                or path.stat().st_size != member['bytes'] or sha(path) != member['sha256']):
            raise ValueError('Source client verification failed: '+name)
    # Only the TLS-context injection changes a pre-existing packaged source.
    # Refuse to replace a newer/different desktop source accidentally.
    desktop = (source/'desktop_launcher.py').read_text(encoding='utf-8')
    if desktop.count('def main():') != 1 or desktop.count('lobby = CommunityClient(hostname,port,server_address,policy)') != 1:
        raise ValueError('Desktop producer changed; review the adapter before rebuilding.')
    desktop = desktop.replace('def main():', 'def main(*, ssl_context=None):').replace(
        'lobby = CommunityClient(hostname,port,server_address,policy)',
        'lobby = CommunityClient(hostname,port,server_address,policy,ssl_context=ssl_context)')
    output.mkdir(parents=True)
    for member in manifest['files']:
        src, dst = source/member['path'], output/member['path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        if member['path'] == 'desktop_launcher.py':
            dst.write_text(desktop, encoding='utf-8', newline='\n')
            member.update(bytes=dst.stat().st_size, sha256=sha(dst))
        else:
            # Same-volume links refer only to immutable published payloads.
            try:
                os.link(src, dst)
            except OSError:
                import shutil
                shutil.copyfile(src, dst)
    support = {'platform': 'linux-x86_64-through-steam-proton', 'native_linux_game': False,
               'source_manifest_sha256': expected_source_sha256,
               'linux_launcher': '6 focused handoff and log-owner checks passed on Ubuntu 24.04 / Python 3.12',
               'windows_regression': '8 desktop and transport checks passed',
               'runtime_qualification': 'Steam/Proton game, Steam persona and UE4SS gameplay are not yet qualified',
               'server_included': False, 'setup': 'README-Linux.txt'}
    (output/'linux-support.json').write_text(json.dumps(support, indent=2)+'\n', encoding='utf-8')
    for name in ADDITIONS:
        if name.casefold() in seen:
            raise ValueError('Source already includes a Linux adapter; review the new producer.')
        (output/name).write_bytes((ROOT/name).read_bytes())
    for name in (*ADDITIONS, 'linux-support.json'):
        path = output/name
        manifest['files'].append({'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)})
    manifest['revision_id'] = output.name
    manifest['platform'] = support['platform']
    (output/'package-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    expected = {item['path']: item for item in manifest['files']}
    expected['package-manifest.json'] = {'bytes': (output/'package-manifest.json').stat().st_size,
                                         'sha256': sha(output/'package-manifest.json')}
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'x:gz', compresslevel=6) as stream:
        for name, member in sorted(expected.items()):
            path = output/name
            if path.stat().st_size != member['bytes'] or sha(path) != member['sha256']:
                raise ValueError('Output changed before archiving: '+name)
            info = stream.gettarinfo(str(path), output.name+'/'+name)
            # Never archive a hardlink to an external package, even when the
            # filesystem payload itself is shared with an immutable source.
            info.type, info.linkname = tarfile.REGTYPE, ''
            info.size = member['bytes']
            info.mode = 0o755 if name == 'Start Community Starter.sh' else 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            with path.open('rb') as payload:
                stream.addfile(info, payload)
    with tarfile.open(archive, 'r:gz') as stream:
        examined = set()
        for info in stream:
            if not info.isfile() or not info.name.startswith(output.name+'/'):
                raise ValueError('Non-regular archive entry.')
            name = info.name[len(output.name)+1:]
            if name in examined or name not in expected or info.size != expected[name]['bytes']:
                raise ValueError('Archive inventory mismatch.')
            examined.add(name)
            with stream.extractfile(info) as payload:
                if hashlib.file_digest(payload, 'sha256').hexdigest() != expected[name]['sha256']:
                    raise ValueError('Archive member failed SHA256: '+name)
            if name == 'Start Community Starter.sh' and info.mode != 0o755:
                raise ValueError('Linux launch script is not executable.')
        if examined != set(expected):
            raise ValueError('Archive is incomplete.')
    if sha(source/'package-manifest.json') != expected_source_sha256:
        raise ValueError('Source manifest changed during build.')
    return {'status': 'launcher_candidate_archive_verified', 'output': str(output), 'archive': str(archive),
            'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size,
            'manifest_sha256': sha(output/'package-manifest.json'), 'members': len(expected),
            'source': str(source), 'source_manifest_sha256': expected_source_sha256,
            'scope': support['runtime_qualification']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--proof', type=Path, required=True)
    args = parser.parse_args()
    began = time.monotonic()
    proof = build(args.source, args.source_sha256, args.output, args.archive)
    proof['elapsed_seconds'] = time.monotonic()-began
    args.proof.parent.mkdir(parents=True, exist_ok=True)
    with args.proof.open('x', encoding='utf-8') as stream:
        json.dump(proof, stream, indent=2)
        stream.write('\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
