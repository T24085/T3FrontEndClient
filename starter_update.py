"""Install signed Community Starter changes before importing the desktop launcher."""
from base64 import b64decode
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener
import uuid

from starter_update_signing import verify


CHANNEL = 'windows-r12-v1'
DIRECT_CHANNEL = 'windows-direct-r12-v1'
BASE_URL = 'https://github.com/T24085/T3FrontEndClient/releases/download/starter-updates-v1/'
DIRECT_BASE_URL = 'https://github.com/T24085/T3FrontEndClient/releases/download/direct-starter-updates-v1/'
INDEX = 'starter-update.json'
ALLOWED = frozenset({
    'bulk_asset_cache.py', 'bulk_verification_receipts.py', 'client.py', 'client_bootstrap.py',
    'client_preparation.py', 'community_game.py', 'community_transport.py', 'desktop_launcher.py',
    'map_catalog.py', 'map_sync.py', 'map_sync_contract.py', 'player_names.py', 'player_profile.py',
    'runtime_health.py', 'server_access.py', 'server_access_contract.py', 'startup_paths.py',
    'startup_progress.py', 'startup_timing.py', 'steam_identity.py', 'verified_file_cache.py',
    'lua/client.lua', 'lua/damnation_water.lua', 'lua/spectator_client.lua', 'lua/spectator_materials.lua',
})
UPDATE_CHANNELS = {
    CHANNEL: (BASE_URL, ALLOWED),
    DIRECT_CHANNEL: (DIRECT_BASE_URL, ALLOWED | {'direct_client.py', 'direct_network.py'}),
}
MAX_INDEX = 32768
MAX_FILE = 1024 * 1024
MAX_TOTAL = 8 * MAX_FILE
MAX_LIFETIME = 180 * 86400
INVENTORY = 'package-manifest.json'
STATE_DIRECTORY = '.starter-update'


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode_index(raw, *, channel=CHANNEL, verifier=verify, now=None):
    if len(raw) > MAX_INDEX:
        raise ValueError('Update index exceeds its size limit.')
    envelope = json.loads(raw)
    if not isinstance(envelope, dict) or envelope.keys() != {'payload', 'signature'}:
        raise ValueError('Invalid signed update envelope.')
    payload = b64decode(envelope['payload'], validate=True)
    signature = b64decode(envelope['signature'], validate=True)
    if not verifier(payload, signature):
        raise ValueError('Update signature is invalid.')
    index = json.loads(payload)
    if not isinstance(index, dict) or index.keys() != {'channel', 'revision', 'issued', 'expires', 'files'}:
        raise ValueError('Unsupported update index.')
    if payload != encoded(index) or index['channel'] != channel:
        raise ValueError('Unsupported update channel or metadata encoding.')
    current = int(time.time() if now is None else now)
    revision, issued, expires = (index[key] for key in ('revision', 'issued', 'expires'))
    if (type(revision) is not int or not 1 <= revision < 2**31
            or type(issued) is not int or type(expires) is not int
            or not 0 < expires - issued <= MAX_LIFETIME or not issued <= current + 300 or expires <= current):
        raise ValueError('Update revision or validity period is invalid.')
    files = index['files']
    if not isinstance(files, dict) or not files.keys() <= UPDATE_CHANNELS[channel][1]:
        raise ValueError('Update contains an unsupported file path.')
    for row in files.values():
        if (not isinstance(row, dict) or row.keys() != {'bytes', 'sha256'}
                or type(row['bytes']) is not int or not 0 < row['bytes'] <= MAX_FILE
                or not isinstance(row['sha256'], str) or re.fullmatch('[a-f0-9]{64}', row['sha256']) is None):
            raise ValueError('Invalid update file inventory.')
    if sum(row['bytes'] for row in files.values()) > MAX_TOTAL:
        raise ValueError('Update exceeds its total size limit.')
    return index


class GitHubRedirect(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if (url.scheme != 'https' or url.netloc not in
                {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}):
            raise ValueError('Unexpected Community Starter download redirect.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetcher(*, channel=CHANNEL, ssl_context=None):
    base_url = UPDATE_CHANNELS[channel][0]
    opener = build_opener(GitHubRedirect(), HTTPSHandler(context=ssl_context))
    deadline = time.monotonic() + 20

    def fetch(name, bound):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError('The Community Starter update check timed out.')
        request = Request(base_url + name, headers={'User-Agent': 'TRIBES3-Community-Starter-r12', 'Cache-Control': 'no-cache'})
        with opener.open(request, timeout=min(4, left)) as response:
            if response.status != 200:
                raise OSError('Update download did not complete.')
            raw = bytearray()
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError('The Community Starter update download timed out.')
                block = response.read(min(65536, bound + 1 - len(raw)))
                if not block:
                    return bytes(raw)
                raw.extend(block)
                if len(raw) > bound:
                    raise ValueError('Update download exceeds its declared size.')

    return fetch


def inside(root, name):
    path = root / name
    if path.resolve() != path or path.is_symlink():
        raise ValueError('Update path is redirected outside its package location.')
    return path


def atomic_write(path, raw):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class StarterAlreadyOpen(RuntimeError):
    pass


@contextmanager
def startup_lock(root):
    import msvcrt

    state = inside(root, STATE_DIRECTORY)
    state.mkdir(exist_ok=True)
    with inside(state, 'instance.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise StarterAlreadyOpen('Community Starter is already open for this folder.') from exc
        yield state


def recover(root, state, *, channel=CHANNEL):
    pending = inside(state, 'pending')
    if not pending.exists():
        return False
    journal = json.loads(inside(pending, 'journal.json').read_bytes())
    files, revision = journal['files'], journal['revision']
    if (not files.keys() <= UPDATE_CHANNELS[channel][1] | {INVENTORY}
            or INVENTORY not in files or type(revision) is not int):
        raise ValueError('Invalid Starter update recovery journal.')
    originals = {name: inside(pending, name).read_bytes() for name in files}
    if any(sha(raw) != files[name] for name, raw in originals.items()):
        raise ValueError('The Starter update backup is incomplete.')
    for name, raw in originals.items():
        atomic_write(inside(root, name), raw)
    atomic_write(inside(state, 'rejected.json'), encoded(revision))
    retired = inside(state, 'recovered-' + uuid.uuid4().hex)
    os.replace(pending, retired)
    shutil.rmtree(retired, ignore_errors=True)
    return True


def accept(state):
    pending = inside(state, 'pending')
    previous = inside(state, 'previous')
    if previous.exists():
        shutil.rmtree(previous)
    os.replace(pending, previous)


def prepare(root, state, *, channel=CHANNEL, fetch=None, verifier=verify):
    fetch = fetch or fetcher(channel=channel)
    inventory = inside(root, INVENTORY)
    original = inventory.read_bytes()
    manifest = json.loads(original)
    if ('direct_host_contract' in manifest) != (channel == DIRECT_CHANNEL):
        raise ValueError('Update channel does not match this Starter package.')
    revision = manifest.get('starter_update_revision', 0)
    rejected = inside(state, 'rejected.json')
    rejected_revision = json.loads(rejected.read_bytes()) if rejected.exists() else 0
    index = decode_index(fetch(INDEX, MAX_INDEX), channel=channel, verifier=verifier)
    if index['revision'] <= max(revision, rejected_revision):
        return False
    rows = {row['path']: row for row in manifest['files']}
    frozen = {name for names in manifest['map_runtime'].values() for name in names}
    files = index['files']
    if not files.keys() <= rows.keys() or files.keys() & frozen:
        raise ValueError('Update does not match this Starter package.')
    if not set(manifest.get('starter_update_files', [])) <= files.keys():
        raise ValueError('Update is missing files managed by a previous revision.')
    changes, originals = {}, {}
    for name, row in files.items():
        target = inside(root, name)
        previous = target.read_bytes()
        if (len(previous), sha(previous)) != (rows[name]['bytes'], rows[name]['sha256']):
            raise ValueError('Starter file differs from its inventory: ' + name)
        if (len(previous), sha(previous)) == (row['bytes'], row['sha256']):
            continue
        raw = fetch('starter-file-' + row['sha256'] + '.bin', row['bytes'])
        if (len(raw), sha(raw)) != (row['bytes'], row['sha256']):
            raise ValueError('Starter update file failed verification: ' + name)
        if name.endswith('.py'):
            compile(raw, name, 'exec')
        changes[name], originals[name] = raw, previous
        rows[name].update(row)
    manifest.update(starter_update_revision=index['revision'], starter_update_files=sorted(files))
    changes[INVENTORY], originals[INVENTORY] = encoded(manifest), original
    stage = inside(state, 'staging-' + uuid.uuid4().hex)
    stage.mkdir()
    pending = inside(state, 'pending')
    try:
        for name, raw in originals.items():
            backup = stage / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(backup, raw)
        atomic_write(stage / 'journal.json', encoded({'revision': index['revision'],
                                                      'files': {name: sha(raw) for name, raw in originals.items()}}))
        os.replace(stage, pending)
        try:
            for name, raw in changes.items():
                target = inside(root, name)
                if target.read_bytes() != originals[name]:
                    raise ValueError('Starter files changed during update preparation.')
                atomic_write(target, raw)
        except BaseException:
            recover(root, state, channel=channel)
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
    return True


def run_startup(root, launch, *, channel=CHANNEL, ssl_context=None):
    """Update and launch under the same per-package lock."""
    with startup_lock(root) as state:
        if recover(root, state, channel=channel):
            print('Restored the previous Starter after an interrupted update.')
        applied = False
        try:
            fetch = fetcher(channel=channel, ssl_context=ssl_context)
            applied = prepare(root, state, channel=channel, fetch=fetch)
        except Exception as exc:
            print('Starter update skipped:', exc)
            recover(root, state, channel=channel)

        try:
            launch(on_ready=(lambda: accept(state)) if applied else None)
        except BaseException as exc:
            if applied and recover(root, state, channel=channel):
                raise RuntimeError('The previous Starter was restored. Reopen Starter to continue.') from exc
            raise
        if applied:
            recover(root, state, channel=channel)
