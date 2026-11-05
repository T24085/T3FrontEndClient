"""Build a separate candidate from a verified modern client and canonical entry."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from community_maps import declared_maps

ROOT = Path(__file__).resolve().parent
SOURCE = Path(r'D:\Tribes3-Research\releases\staging\Tribes3-Community-Windows-Worldbuilding-20261102-r1')
SOURCE_MANIFEST_SHA256 = '740081ed79694c486fcff871b4e5ff3329100e5f7407eaf01985d3ed4c44a009'
OUTPUT = ROOT / 'dynamic-client-development'
CANONICAL_HELPERS = ('player_profile.py', 'client_bootstrap.py', 'bulk_verification_receipts.py', 'runtime_health.py', 'startup_progress.py', 'startup_paths.py', 'startup_timing.py',
                     'client_preparation.py', 'bulk_asset_cache.py', 'verified_file_cache.py')
SPECTATOR_RUNTIME_FILES = ('lua/spectator_client.lua', 'lua/spectator_materials.lua')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require_spectator_runtime(manifest, verified_files):
    """Validate feature closure against verified inventory, never ambient files."""
    contract = manifest.get('spectator_contract')
    if contract not in (None, 'native-spectator-v1'):
        raise ValueError('Unsupported source spectator contract.')
    if contract:
        missing = [name for name in SPECTATOR_RUNTIME_FILES if name not in verified_files]
        if missing:
            raise ValueError('Source spectator contract is missing its runtime: ' + ', '.join(missing))


def copy_spectator_runtime(manifest, output):
    """Use current camera policy when wrapping a verified spectator package."""
    if manifest.get('spectator_contract') == 'native-spectator-v1':
        for name in SPECTATOR_RUNTIME_FILES:
            shutil.copyfile(ROOT / name, output / name)


def verified_source(source):
    manifest = json.loads((source / 'package-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('startup_contract') != 'prepared-client-v1':
        raise ValueError('A modern prepared-client-v1 source package is required.')
    declared_maps(manifest)
    files = {}
    for item in manifest['files']:
        name = item['path']
        rel = PurePosixPath(name)
        if (rel.is_absolute() or '..' in rel.parts or ':' in name or '\\' in name
                or not rel.parts or rel.as_posix() != name):
            raise ValueError('Unsafe source inventory path')
        if name.casefold() in files:
            raise ValueError('Duplicate source inventory path')
        path = source.joinpath(*rel.parts).resolve(strict=True)
        if source not in path.parents:
            raise ValueError('Source inventory escapes package')
        if not path.is_file() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Client source failed verification: ' + name)
        files[name.casefold()] = (name, path)
    required = ('client.py', 'connection-policy.json', 'lib/client_support.py', 'lib/owned_native_session.py',
                'client_preparation.py', 'startup_timing.py', 'startup_paths.py', 'lua/client.lua')
    if any(name not in files for name in required):
        raise ValueError('Source package is missing modern client runtime dependencies.')
    require_spectator_runtime(manifest, files)
    return manifest, tuple(files.values())


def candidate_manifest(source_manifest, output):
    """Preserve producer-owned map/runtime/shared-content facts without reinterpretation."""
    manifest = dict(source_manifest)
    manifest['build_id'] = 'dynamic-client-development'
    manifest['files'] = [dict(path=path.relative_to(output).as_posix(), bytes=path.stat().st_size, sha256=sha(path))
                         for path in sorted(output.rglob('*'))
                         if path.is_file() and path != output / 'package-manifest.json']
    return manifest


def build_candidate(source, output):
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if source in output.parents:
        raise ValueError('Candidate output must be outside the verified source package.')
    if output.exists():
        raise ValueError('Output already exists; choose a new candidate directory.')
    if source == SOURCE and sha(source / 'package-manifest.json') != SOURCE_MANIFEST_SHA256:
        raise ValueError('The pinned modern source manifest changed.')
    manifest, files = verified_source(source)
    output.mkdir(exist_ok=False)
    for name, original in files:
        if name in ('connection.json', 'package-manifest.json'):
            continue
        target = output.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    shutil.copyfile(ROOT / 'client_entry.py', output / 'client.py')
    copy_spectator_runtime(manifest, output)
    shutil.copyfile(ROOT / 'dynamic_destination.py', output / 'lib/dynamic_destination.py')
    for name in CANONICAL_HELPERS:
        shutil.copyfile(ROOT / name, output / name)
    provenance = {'source_build_id': manifest['build_id'],
                  'source_manifest_sha256': sha(source / 'package-manifest.json'),
                  'source_client_sha256': sha(source / 'client.py'),
                  'canonical_entry': 'client_entry.py', 'canonical_entry_sha256': sha(ROOT / 'client_entry.py'),
                  'generated_client_sha256': sha(output / 'client.py'),
                  'status': 'unreleased; lobby and gameplay regression qualification required'}
    (output / 'dynamic-client-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    (output / 'README-FIRST.txt').write_text('Development candidate. Lobby, gameplay and spectator qualification are required before distribution.\n', encoding='utf-8')
    (output / 'package-manifest.json').write_text(json.dumps(candidate_manifest(manifest, output), indent=2) + '\n', encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=OUTPUT,
                        help='New directory; existing outputs are never overwritten.')
    args = parser.parse_args()
    print('Separate dynamic client prepared:', build_candidate(args.source, args.output))


if __name__ == '__main__':
    main()
