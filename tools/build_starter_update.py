"""Build a signed, cumulative Community Starter index and its content-addressed files."""
import argparse
from base64 import b64decode, b64encode
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from direct_update_contract import LINUX_INDEX
from starter_update import (CHANNEL, DIRECT_CHANNEL, INDEX, LINUX_CHANNEL, LINUX_CHUNK_BYTES,
                            MAX_FILE, UPDATE_CHANNELS, decode_index, encoded, sha)


def client_entry_payload(raw, root):
    """Embed a Lua dependency without adding a new path to older updater allowlists."""
    module = root/'runtime-fixes/projectile_inheritance.lua'
    if module.resolve(strict=True) != module:
        raise ValueError('Linked source is not permitted: projectile inheritance runtime')
    marker = b'_SIGNED_PROJECTILE_INHERITANCE_MODULE = None'
    if raw.count(marker) != 1:
        raise ValueError('Missing projectile inheritance slot in the canonical client entry.')
    literal = ascii(module.read_text(encoding='utf-8')).encode('ascii')
    return raw.replace(marker, b'_SIGNED_PROJECTILE_INHERITANCE_MODULE = ' + literal)


def bundled_client_entry(raw, weather):
    # Older signed-updater bootstraps cannot add a new Lua inventory path.
    marker = b'_SIGNED_WEATHER_MODULE = None'
    if raw.count(marker) != 1 or not weather:
        raise ValueError('The canonical Starter weather runtime cannot be bundled.')
    return raw.replace(marker, b'_SIGNED_WEATHER_MODULE = ' + repr(weather).encode('ascii'), 1)


def soundtrack_entry(raw, root):
    source = root/'map_soundtracks.py'
    if source.resolve(strict=True) != source:
        raise ValueError('Linked soundtrack source is not permitted.')
    marker = b'_SIGNED_SOUNDTRACK_PLAYER = None'
    if raw.count(marker) != 1:
        raise ValueError('Missing canonical soundtrack player marker.')
    module = source.read_bytes()
    return raw.replace(marker, module + b'\n_SIGNED_SOUNDTRACK_PLAYER = soundtrack_player', 1)


def bundled_boundary_launcher(raw, root):
    source = root / 'boundary_controls.py'
    if source.resolve(strict=True) != source:
        raise ValueError('Linked source is not permitted: boundary controls')
    marker = (b'from boundary_controls import BoundaryDialog, mode_selection, mode_values, '
              b'summary as boundary_summary, with_mode')
    if raw.count(marker) != 1:
        raise ValueError('Missing canonical launcher boundary import.')
    return raw.replace(marker, source.read_bytes() + b'\nboundary_summary = summary', 1)


def source_payload(root, name, *, windows_revision=None):
    if name in ('direct_client.py', 'direct_network.py'):
        source = root / 'experimental/direct-hosting/src' / name
    else:
        source = root / ('client_entry.py' if name == 'client.py' else name)
    if source.resolve(strict=True) != source:
        raise ValueError('Linked source is not permitted: ' + name)
    raw = source.read_bytes()
    if name == 'client.py':
        raw = client_entry_payload(raw, root)
        weather = root / 'lua/weather.lua'
        if weather.resolve(strict=True) != weather:
            raise ValueError('Linked weather runtime source is not permitted.')
        raw = bundled_client_entry(raw, weather.read_bytes())
        raw = soundtrack_entry(raw, root)
    if name == 'desktop_launcher.py':
        raw = bundled_boundary_launcher(raw, root)
    if name == 'ubuntu_starter.py':
        marker = b'SOURCE_STARTER_REVISION = None'
        if raw.count(marker) != 1:
            raise ValueError('Missing Ubuntu launcher source revision marker.')
        raw = raw.replace(marker, f'SOURCE_STARTER_REVISION = {windows_revision}'.encode('ascii'), 1)
    return raw


def add_payload(name, raw, files, payloads, *, channel):
    if not 0 < len(raw) <= MAX_FILE:
        raise ValueError('Unsupported Starter update file size: ' + name)
    if name.endswith(('.py', '.pyw')):
        compile(raw, name, 'exec')
    digest = sha(raw)
    files[name] = {'bytes': len(raw), 'sha256': digest}
    pieces = [raw]
    if channel == LINUX_CHANNEL and len(raw) > LINUX_CHUNK_BYTES:
        pieces = [raw[start:start + LINUX_CHUNK_BYTES] for start in range(0, len(raw), LINUX_CHUNK_BYTES)]
        files[name]['chunks'] = [sha(part) for part in pieces]
    for part in pieces:
        payloads['starter-file-' + sha(part) + '.bin'] = part


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--certificate', required=True, help='Current user signing certificate thumbprint')
    parser.add_argument('--channel', choices=UPDATE_CHANNELS, default=CHANNEL)
    parser.add_argument('--previous', type=Path, help='Last published signed index')
    parser.add_argument('--windows-index', type=Path, help='Paired signed Windows Direct index for a Linux update')
    parser.add_argument('files', nargs='*', help='Client package paths to add to the managed inventory')
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Keep update artifacts outside the source checkout.')
    if subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), '-C', str(ROOT),
                                'status', '--porcelain']).strip():
        raise ValueError('Commit the client source before building a signed update.')
    linux = args.channel == LINUX_CHANNEL
    if linux and (args.previous is None or args.windows_index is None):
        parser.error('Linux updates require the previous Linux index and the paired Windows Direct index.')
    if not linux and args.windows_index is not None:
        parser.error('The paired Windows index is used only with the Linux channel.')
    windows_revision = (decode_index(args.windows_index.read_bytes(), channel=DIRECT_CHANNEL)['revision']
                        if linux else None)
    paths = set(args.files)
    revision = 1
    if args.previous:
        raw = args.previous.read_bytes()
        envelope = json.loads(raw)
        # The publisher can renew a previously signed index after it expires.
        issued = json.loads(b64decode(envelope['payload'], validate=True))['issued']
        previous = decode_index(raw, channel=args.channel, now=issued)
        paths.update(previous['files'])
        revision = previous['revision'] + 1
    projectile_dependencies = {'client.py', 'community_game.py', 'community_transport.py',
                               'desktop_launcher.py', 'player_profile.py', 'runtime_health.py', 'lua/client.lua'}
    if args.channel in (DIRECT_CHANNEL, LINUX_CHANNEL):
        projectile_dependencies.add('direct_client.py')
    if paths & projectile_dependencies:
        paths.update(projectile_dependencies)
    if paths & {'client.py', 'lua/client.lua'}:
        paths.update(('client.py', 'lua/client.lua'))
    if not paths or not paths <= UPDATE_CHANNELS[args.channel][1]:
        raise ValueError('Select existing supported Starter package files.')
    files, payloads = {}, {}
    for name in sorted(paths):
        raw = source_payload(ROOT, name, windows_revision=windows_revision)
        add_payload(name, raw, files, payloads, channel=args.channel)
    now = int(time.time())
    payload = encoded({'channel': args.channel, 'revision': revision, 'issued': now, 'expires': now + 90 * 86400,
                       'files': files})
    with tempfile.TemporaryDirectory() as directory:
        unsigned = Path(directory) / 'payload.json'
        signature = Path(directory) / 'signature.bin'
        unsigned.write_bytes(payload)
        subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File',
                        str(ROOT / 'tools/sign_starter_update.ps1'), '-Thumbprint', args.certificate,
                        '-Payload', str(unsigned), '-Signature', str(signature)], check=True)
        index = encoded({'payload': b64encode(payload).decode(), 'signature': b64encode(signature.read_bytes()).decode()})
    assert decode_index(index, channel=args.channel)['revision'] == revision
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        (output / name).write_bytes(raw)
    (output / (LINUX_INDEX if linux else INDEX)).write_bytes(index)
    print(f'Signed Starter revision {revision} with {len(files)} managed file(s).', flush=True)


if __name__ == '__main__':
    main()
