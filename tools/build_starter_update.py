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
from starter_update import CHANNEL, INDEX, MAX_FILE, UPDATE_CHANNELS, decode_index, encoded, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--certificate', required=True, help='Current user signing certificate thumbprint')
    parser.add_argument('--channel', choices=UPDATE_CHANNELS, default=CHANNEL)
    parser.add_argument('--previous', type=Path, help='Last published signed index')
    parser.add_argument('files', nargs='*', help='Client package paths to add to the managed inventory')
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Keep update artifacts outside the source checkout.')
    if subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(), '-C', str(ROOT),
                                'status', '--porcelain']).strip():
        raise ValueError('Commit the client source before building a signed update.')
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
    if not paths or not paths <= UPDATE_CHANNELS[args.channel][1]:
        raise ValueError('Select existing supported Starter package files.')
    files, payloads = {}, {}
    for name in sorted(paths):
        if name in ('direct_client.py', 'direct_network.py'):
            source = ROOT / 'experimental/direct-hosting/src' / name
        else:
            source = ROOT / ('client_entry.py' if name == 'client.py' else name)
        if source.resolve(strict=True) != source:
            raise ValueError('Linked source is not permitted: ' + name)
        raw = source.read_bytes()
        if not 0 < len(raw) <= MAX_FILE:
            raise ValueError('Unsupported Starter update file size: ' + name)
        if name.endswith('.py'):
            compile(raw, name, 'exec')
        digest = sha(raw)
        files[name] = {'bytes': len(raw), 'sha256': digest}
        payloads['starter-file-' + digest + '.bin'] = raw
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
    (output / INDEX).write_bytes(index)
    print(f'Signed Starter revision {revision} with {len(files)} managed file(s).', flush=True)


if __name__ == '__main__':
    main()
