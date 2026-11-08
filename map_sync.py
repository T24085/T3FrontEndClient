"""Fetch and stage immutable cooked-map revisions without changing the client ZIP's files."""
import gzip
from contextlib import closing
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import threading
import uuid
import zlib

from bulk_asset_cache import DISK_RESERVE_BYTES
from community_transport import CommunityError, PinnedHTTPSConnection
from map_sync_contract import (CATALOG_ROUTE, CATALOG_VERSION, CHUNK, FILE_ROUTE, MANIFEST_ROUTE, MAX_MANIFEST, SHA, VERSION,
                               cooked_rows, encode, map_catalog)
from community_maps import BY_ID, declared_definitions
from verified_file_cache import digest


def bounded_read(stream):
    raw = stream.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise ValueError('Map inventory exceeds its size limit.')
    return raw


def cache_path(workspace, name):
    root = Path(workspace) / 'map-downloads'
    path = root / name
    if path.resolve() != path or path.is_symlink() or root.is_symlink() or root.is_junction():
        raise ValueError('Map download cache must be a private workspace directory.')
    return path


def overlay(package, remote):
    if not isinstance(remote, dict) or type(remote.get('format')) is not int:
        raise ValueError('Unsupported map download inventory.')
    version = remote['format']
    fields = {'format', 'maps', 'files', 'shared_content'}
    if version == CATALOG_VERSION:
        fields.update(('community_maps', 'map_definitions'))
    if version not in (VERSION, CATALOG_VERSION) or set(remote) != fields:
        raise ValueError('Unsupported map download inventory.')
    rows = cooked_rows(remote['files'])
    bundled = [row for row in package['files'] if row['path'].startswith('content/')]
    local_files = {(row['sha256'], row['bytes']): row['path'] for row in bundled}
    local_paths = {row['path']: row for row in bundled}
    sources = {}
    for name, row in rows.items():
        key = (row['sha256'], row['bytes'])
        sources[name] = name if local_paths.get(name) == row else local_files.get(key)
    effective = dict(package, shared_content=remote['shared_content'],
                     files=[row for row in package['files'] if not row['path'].startswith('content/')] + list(rows.values()))
    custom = {}
    if version == CATALOG_VERSION:
        custom = remote['map_definitions']
        effective.update(community_maps=remote['community_maps'], map_definitions=custom)
        selected = declared_definitions(effective)
        effective['map_runtime'] = {name: package['map_runtime'].get(name, []) for name in selected}
        if any(name not in package['map_runtime'] and name in BY_ID for name in selected):
            raise ValueError('Server maps require a newer Starter or matching base game.')
    catalog = map_catalog(effective)
    if catalog != remote['maps']:
        raise ValueError('Server maps require a newer Starter or matching base game.')
    return rows, sources, catalog, custom


def load_overlay(workspace, revision, package):
    if not SHA.fullmatch(revision):
        raise ValueError('Invalid map revision.')
    with cache_path(workspace, revision + '.json').open('rb') as stream:
        raw = bounded_read(stream)
    if hashlib.sha256(raw).hexdigest() != revision:
        raise ValueError('The cached map revision changed. Reopen Starter to refresh it.')
    rows, sources, catalog, custom = overlay(package, json.loads(raw))
    return [(row, sources[name], cache_path(workspace, row['sha256'] + '.asset') if sources[name] is None else None)
            for name, row in rows.items()], catalog, custom


class MapSync:
    def __init__(self, lobby, package, workspace):
        self.lobby = lobby
        self.package = Path(package)
        self.workspace = Path(workspace)
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.status = ''
        self.current = (None, {})
        self.bundled = None
        self.thread = None
        self.available = False
        self.version = None

    def start(self, version):
        self.available = type(version) is int and version in (VERSION, CATALOG_VERSION)
        self.version = version if self.available else None
        if self.available and (self.thread is None or not self.thread.is_alive()):
            self.thread = threading.Thread(target=self._background, name='map-downloads', daemon=True)
            self.thread.start()

    def _background(self):
        try:
            self.refresh()
        except (CommunityError, ValueError, TypeError, KeyError, OSError) as exc:
            self.status = 'Map check paused. ' + str(exc)

    def _connection(self):
        lobby = self.lobby
        return PinnedHTTPSConnection(lobby.hostname, lobby.port, lobby.server_address, context=lobby.context,
                                     timeout=15, source_address=(lobby.test_source, 0) if lobby.test_source else None)

    def _inventory(self):
        try:
            with closing(self._connection()) as connection:
                path = CATALOG_ROUTE if self.version == CATALOG_VERSION else MANIFEST_ROUTE
                connection.request('GET', path, headers={'Host': self.lobby.authority})
                with connection.getresponse() as response:
                    if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
                        raise CommunityError('Server map inventory is unavailable.')
                    return json.loads(bounded_read(response))
        except (http.client.HTTPException, OSError) as exc:
            raise CommunityError('Could not securely download the map inventory.') from exc

    def _download(self, row, output):
        sha, length = row['sha256'], row['bytes']
        for attempt in range(30):
            self._check_cancelled()
            with closing(self._connection()) as connection:
                connection.request('GET', FILE_ROUTE + sha, headers={'Host': self.lobby.authority})
                with connection.getresponse() as response:
                    if response.status != 503:
                        if (response.status != 200 or response.getheader('Content-Type') != 'application/octet-stream'
                                or response.getheader('Content-Encoding') != 'gzip'):
                            raise CommunityError('A requested map file is unavailable. Try joining again.')
                        self._write_verified(response, output, sha, length)
                        return
            self.cancelled.wait(min(6, 1 + attempt) + (uuid.uuid4().int % 1000) / 1000)
        raise CommunityError('The map download server is busy. Try joining again.')

    def _write_verified(self, response, output, sha, length):
        temporary = output.with_name(output.name + '.' + uuid.uuid4().hex + '.tmp')
        checksum = hashlib.sha256()
        try:
            with temporary.open('xb') as stream, gzip.GzipFile(fileobj=response) as incoming:
                remaining = length
                while chunk := incoming.read(min(CHUNK, remaining + 1)):
                    self._check_cancelled()
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ValueError('Map download exceeded its declared size.')
                    stream.write(chunk)
                    checksum.update(chunk)
            if remaining or checksum.hexdigest() != sha:
                raise ValueError('Map download failed SHA-256 verification.')
            try:
                if os.name == 'nt':
                    os.rename(temporary, output)
                else:
                    os.link(temporary, output)
            except FileExistsError:
                if output.stat().st_size != length or digest(output) != sha:
                    os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)

    def _check_cancelled(self):
        if self.cancelled.is_set():
            raise CommunityError('Map download cancelled.')

    def bundled_catalog(self):
        if self.bundled is None:
            self.bundled = map_catalog(json.loads((self.package / 'package-manifest.json').read_bytes()))
        return self.bundled

    def revision_for(self, map_id, fingerprint):
        revision, catalog = self.current
        if catalog.get(map_id) == fingerprint:
            return revision
        if self.bundled_catalog().get(map_id) == fingerprint:
            return None
        if self.available:
            revision, catalog = self.refresh(required=(map_id, fingerprint))
            if catalog.get(map_id) == fingerprint:
                return revision
        raise CommunityError('Your map files do not match this match. Update the community client.')

    def refresh(self, *, required=None):
        with self.lock:
            if required and self.current[1].get(required[0]) == required[1]:
                return self.current
            self._check_cancelled()
            self.status = 'Checking for map updates…'
            try:
                return self._refresh(required)
            except (OSError, EOFError, ValueError, TypeError, KeyError, http.client.HTTPException, zlib.error) as exc:
                self.status = 'Map check paused. ' + str(exc)
                raise CommunityError('Map update failed. ' + str(exc)) from exc
            except CommunityError as exc:
                self.status = 'Map check paused. ' + str(exc)
                raise

    def _refresh(self, required):
        package = json.loads((self.package / 'package-manifest.json').read_bytes())
        remote = self._inventory()
        rows, sources, catalog, _ = overlay(package, remote)
        if required and catalog.get(required[0]) != required[1]:
            raise CommunityError('The server map version changed. Refresh the lobby and try again.')
        if catalog == self.bundled_catalog():
            self.current = (None, catalog)
        else:
            raw = encode(remote)
            revision = hashlib.sha256(raw).hexdigest()
            if self.current[0] != revision:
                self._cache_revision(rows, sources, revision, raw)
            self.current = (revision, catalog)
        self.status = 'Maps up to date.'
        return self.current

    def _cache_revision(self, rows, sources, revision, raw):
        needed = {row['sha256']: row for name, row in rows.items() if sources[name] is None}
        manifest_path = cache_path(self.workspace, revision + '.json')
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        pending = []
        for sha, row in needed.items():
            self._check_cancelled()
            path = cache_path(self.workspace, sha + '.asset')
            if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != sha:
                pending.append((row, path))
        size = sum(row['bytes'] for row, _ in pending)
        if size and shutil.disk_usage(manifest_path.parent).free < DISK_RESERVE_BYTES + size:
            raise CommunityError('Free up space on the game workspace drive to download map updates.')
        for number, (row, path) in enumerate(pending, 1):
            self.status = f'Downloading map updates ({number:,}/{len(pending):,} files)…'
            self._download(row, path)
        self._check_cancelled()
        temporary = manifest_path.with_name(manifest_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
            os.replace(temporary, manifest_path)
        finally:
            temporary.unlink(missing_ok=True)
