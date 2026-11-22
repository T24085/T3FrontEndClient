"""Fetch and stage immutable cooked-map revisions without changing the client ZIP's files."""
import gzip
from contextlib import closing, contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import ssl
import threading
import uuid
import zlib
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from bulk_asset_cache import DISK_RESERVE_BYTES
from community_transport import CommunityError, PinnedHTTPSConnection
from map_sync_contract import (CATALOG_ROUTE, CATALOG_VERSION, CHUNK, FILE_ROUTE, MANIFEST_ROUTE, MAX_MANIFEST, SHA, VERSION,
                               MAP_ARCHIVE_ASSETS, MAP_ARCHIVE_NAME, OBJECTIVES_HEADER,
                               SESSION_CORE, SESSION_INDEX, SESSION_MAP, SESSION_SHARED, SESSION_VERSION,
                               cooked_rows, encode, map_catalog, map_groups, map_objective_rows,
                               minimap_payload, session_index, sha256_bytes, valid_sha)
from community_maps import BY_ID, declared_definitions, valid_id
from verified_file_cache import MAX_MERGED_HOST_FILES, digest


NOT_MODIFIED = object()


def bounded_read(stream):
    raw = stream.read(MAX_MANIFEST + 1)
    if len(raw) > MAX_MANIFEST:
        raise ValueError('Map inventory exceeds its size limit.')
    return raw


def cache_path(workspace, name, *, session=False):
    root = Path(workspace) / ('session-map-downloads' if session else 'map-downloads')
    path = root / name
    if path.resolve() != path or path.is_symlink() or root.is_symlink() or root.is_junction():
        raise ValueError('Map download cache must be a private workspace directory.')
    return path


def overlay(package, remote):
    if not isinstance(remote, dict) or type(remote.get('format')) is not int:
        raise ValueError('Unsupported map download inventory.')
    version = remote['format']
    fields = {'format', 'maps', 'files', 'shared_content'}
    if version in (CATALOG_VERSION, SESSION_VERSION):
        fields.update(('community_maps', 'map_definitions'))
        if version == SESSION_VERSION:
            fields.add('runtime')
            if 'minimap' in remote:
                fields.add('minimap')
        if 'objectives' in remote:
            fields.add('objectives')
    if version not in (VERSION, CATALOG_VERSION, SESSION_VERSION) or set(remote) != fields:
        raise ValueError('Unsupported map download inventory.')
    if version == SESSION_VERSION and (not isinstance(remote['maps'], dict) or len(remote['maps']) != 1):
        raise ValueError('The session map inventory must describe a single map.')
    rows = {} if version == SESSION_VERSION and remote['files'] == [] else cooked_rows(remote['files'])
    bundled = [row for row in package['files'] if row['path'].startswith('content/')]
    local_files = {(row['sha256'], row['bytes']): row['path'] for row in bundled}
    local_paths = {row['path']: row for row in bundled}
    effective = dict(package, shared_content=remote['shared_content'],
                     files=[row for row in package['files'] if not row['path'].startswith('content/')] + list(rows.values()))
    custom = {}
    if version in (CATALOG_VERSION, SESSION_VERSION):
        custom = remote['map_definitions']
        effective.update(community_maps=remote['community_maps'], map_definitions=custom)
        selected = declared_definitions(effective)
        effective['map_runtime'] = {name: package['map_runtime'].get(name, []) for name in selected}
        if version == SESSION_VERSION:
            runtime = remote['runtime']
            local = {row['path'] for row in effective['files'] if row['path'].startswith('lua/')}
            if (len(selected) != 1 or not isinstance(runtime, list)
                    or any(not isinstance(path, str) or path not in local for path in runtime)
                    or len(set(runtime)) != len(runtime)):
                raise ValueError('This map requires a newer Starter runtime.')
            effective['map_runtime'] = {next(iter(selected)):runtime}
        elif any(name not in package['map_runtime'] and name in BY_ID for name in selected):
            raise ValueError('Server maps require a newer Starter or matching base game.')
    catalog = map_catalog(effective)
    if catalog != remote['maps']:
        raise ValueError('Server maps require a newer Starter or matching base game.')
    sources = {name: name if local_paths.get(name) == row else local_files.get((row['sha256'], row['bytes']))
               for name, row in rows.items()}
    if 'objectives' in fields:
        authored = map_objective_rows(remote['objectives'], selected)
        rows.update(authored)
        # Objectives are launch inputs pinned to the host revision. Cache them
        # under that digest even when the archive carries identical bytes.
        sources.update(dict.fromkeys(authored))
    if 'minimap' in fields:
        entry = minimap_payload(next(iter(catalog)), remote['minimap'])
        if entry['image'] is not None:
            row = entry['image']
            rows[row['path']] = row
            sources[row['path']] = None
    return rows, sources, catalog, custom


def load_overlay(workspace, revision, package, *, with_minimap=False):
    if not SHA.fullmatch(revision):
        raise ValueError('Invalid map revision.')
    session_path = cache_path(workspace, revision + '.json', session=True)
    # Legacy revisions still work for old hosts and existing prepared sessions.
    session = session_path.exists()
    path = session_path if session else cache_path(workspace, revision + '.json')
    with path.open('rb') as stream:
        raw = bounded_read(stream)
    if hashlib.sha256(raw).hexdigest() != revision:
        raise ValueError('The cached map revision changed. Reopen Starter to refresh it.')
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or session != (manifest.get('format') == SESSION_VERSION):
        raise ValueError('Cached map manifest does not match its storage format.')
    rows, sources, catalog, custom = overlay(package, manifest)
    result = ([(row, sources[name], cache_path(workspace, row['sha256'] + '.asset', session=session)
               if sources[name] is None else None)
               for name, row in rows.items()], catalog, custom, 'objectives' in manifest)
    return (*result, manifest.get('minimap')) if with_minimap else result


def has_session_revision(workspace, revision):
    return isinstance(revision, str) and valid_sha(revision) and cache_path(
        workspace, revision + '.json', session=True).is_file()


@contextmanager
def shared_map_zip(package):
    folders = [package]
    if package.name.casefold() == 'client files':
        folders.append(package.parent)
    for folder in folders:
        path = folder / MAP_ARCHIVE_NAME
        if not path.is_file() or path.is_symlink():
            continue
        try:
            archive = ZipFile(path)
        except (OSError, BadZipFile, UnicodeError):
            continue
        with archive:
            if len(archive.infolist()) <= MAX_MERGED_HOST_FILES + 2:
                yield archive
                return
    yield None


class MapSync:
    def __init__(self, lobby, package, workspace):
        self.lobby = lobby
        self.package = Path(package)
        self.workspace = Path(workspace)
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.status = ''
        self.notice_target = None
        self.notice_active = False
        self.progress = None
        self.current = (None, {})
        self.bundled = None
        self.available = False
        self.version = None
        self.session_enabled = False
        self.map_index_cache = (None, None)
        self.local_version = 0
        self.core_hash = None
        self.prefetch_lock = threading.Lock()
        self.prefetch_target = None
        self.prefetch_thread = None

    def start(self, version, *, session_version=None):
        self.available = type(version) is int and version in (VERSION, CATALOG_VERSION)
        self.version = version if self.available else None
        self.session_enabled = type(session_version) is int and session_version == SESSION_VERSION

    def _connection(self):
        lobby = self.lobby
        return PinnedHTTPSConnection(lobby.hostname, lobby.port, lobby.server_address, context=lobby.context,
                                     timeout=15, source_address=(lobby.test_source, 0) if lobby.test_source else None)

    def _inventory(self):
        path = CATALOG_ROUTE if self.version == CATALOG_VERSION else MANIFEST_ROUTE
        return self._document(path)

    def _document(self, path, expected_hash=None, *, etag=None):
        for attempt in range(3):
            self._check_cancelled()
            try:
                with closing(self._connection()) as connection:
                    headers = self.lobby.request_headers()
                    if path == CATALOG_ROUTE:
                        headers[OBJECTIVES_HEADER] = '1'
                    if etag is not None:
                        headers['If-None-Match'] = etag
                    connection.request('GET', path, headers=headers)
                    with connection.getresponse() as response:
                        if etag is not None and response.status == 304:
                            return NOT_MODIFIED
                        if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
                            raise CommunityError('Server map inventory is unavailable.')
                        remaining = response.length
                        if remaining is not None and remaining > MAX_MANIFEST:
                            raise ValueError('Map inventory exceeds its size limit.')
                        raw = bounded_read(response)
                        if remaining is not None and len(raw) < remaining:
                            raise http.client.IncompleteRead(raw, remaining - len(raw))
                if expected_hash is not None and sha256_bytes(raw) != expected_hash:
                    raise ValueError('The map manifest changed. Refresh the server list and try again.')
                return json.loads(raw)
            except ssl.SSLError as exc:
                raise CommunityError('Could not securely download the map inventory.') from exc
            except (http.client.HTTPException, OSError) as exc:
                if attempt == 2:
                    raise CommunityError('The map catalog download was interrupted. Try again shortly.') from exc
                self.cancelled.wait(attempt + 1)

    def _download(self, row, output, *, check=None):
        check = check or self._check_cancelled
        sha, length = row['sha256'], row['bytes']
        for attempt in range(30):
            check()
            with closing(self._connection()) as connection:
                connection.request('GET', FILE_ROUTE + sha, headers=self.lobby.request_headers())
                with connection.getresponse() as response:
                    if response.status != 503:
                        if (response.status != 200 or response.getheader('Content-Type') != 'application/octet-stream'
                                or response.getheader('Content-Encoding') != 'gzip'):
                            raise CommunityError('A requested map file is unavailable. Try joining again.')
                        self._write_verified(response, output, sha, length, check=check)
                        return
            self.cancelled.wait(min(6, 1 + attempt) + (uuid.uuid4().int % 1000) / 1000)
        raise CommunityError('The map download server is busy. Try joining again.')

    def _write_verified(self, response, output, sha, length, *, check=None):
        with gzip.GzipFile(fileobj=response) as incoming:
            self._write_asset(incoming, output, sha, length, check=check)

    def _write_asset(self, incoming, output, sha, length, *, check=None):
        check = check or self._check_cancelled
        temporary = output.with_name(output.name + '.' + uuid.uuid4().hex + '.tmp')
        checksum = hashlib.sha256()
        try:
            with temporary.open('xb') as stream:
                remaining = length
                while chunk := incoming.read(min(CHUNK, remaining + 1)):
                    check()
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

    def _import_archive_asset(self, archive, row, output, *, check=None):
        try:
            info = archive.getinfo(MAP_ARCHIVE_ASSETS + row['sha256'] + '.asset')
            if (info.is_dir() or info.file_size != row['bytes'] or info.flag_bits & 1
                    or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)):
                return False
            with archive.open(info) as incoming:
                self._write_asset(incoming, output, row['sha256'], row['bytes'], check=check)
        except (KeyError, BadZipFile, zlib.error, EOFError, ValueError, NotImplementedError):
            return False
        return True

    def _check_cancelled(self):
        if self.cancelled.is_set():
            raise CommunityError('Map download cancelled.')

    def bundled_catalog(self):
        if self.bundled is None:
            self.bundled = map_catalog(json.loads((self.package / 'package-manifest.json').read_bytes()))
        return self.bundled

    def revision_for(self, map_id, fingerprint, manifest_hash=None):
        if self.session_enabled:
            return self.sync_map(map_id, fingerprint, manifest_hash)
        if self.available and self.version == CATALOG_VERSION:
            # Weather may change without changing the cooked-map fingerprint.
            revision, _ = self.refresh(required=(map_id, fingerprint), recheck=True)
            return revision
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

    def map_index(self):
        return session_index(self._document(SESSION_INDEX))

    def refresh_map_index(self):
        # Only the Maps catalog worker writes this cache. Downloads use their
        # own manifest requests and can continue while the index is refreshed.
        etag, previous = self.map_index_cache
        document = self._document(SESSION_INDEX, etag=etag)
        if document is NOT_MODIFIED:
            return previous
        rows = session_index(document)
        current = previous if rows == previous else rows
        self.map_index_cache = ('"' + sha256_bytes(encode(document)) + '"', current)
        return current

    def session_path(self, name):
        return cache_path(self.workspace, name, session=True)

    def _receipt(self, map_id):
        if not valid_id(map_id):
            raise ValueError('Invalid map identity.')
        try:
            with self.session_path(f'map-{map_id}.json').open('rb') as stream:
                raw = stream.read(512)
            receipt = json.loads(raw)
            if (isinstance(receipt, dict) and valid_sha(receipt.get('revision'))
                    and valid_sha(receipt.get('manifestHash'))):
                return receipt
        except (OSError, ValueError, RecursionError):
            pass
        return None

    def _cached_session(self, revision, package):
        with self.session_path(revision + '.json').open('rb') as stream:
            raw = bounded_read(stream)
        if sha256_bytes(raw) != revision:
            raise ValueError('The cached map manifest changed.')
        saved = json.loads(raw)
        return raw, overlay(package, saved)

    def _session_document(self, map_id, fingerprint, manifest_hash, package):
        doc = self._document(SESSION_MAP + map_id, manifest_hash)
        fields = {'format', 'id', 'contentHash', 'coreHash', 'sharedHash', 'definition',
                  'files', 'objectives', 'runtime'}
        if (not isinstance(doc, dict) or not fields <= doc.keys() <= fields | {'minimap'}
                or doc['format'] != SESSION_VERSION or doc['id'] != map_id
                or doc['contentHash'] != fingerprint or not valid_sha(doc['coreHash'])
                or not isinstance(doc['files'], list)
                or doc['sharedHash'] is not None and not valid_sha(doc['sharedHash'])):
            raise ValueError('The map manifest does not match this session.')
        if doc['coreHash'] != self.core_hash:
            core = self._document(SESSION_CORE, doc['coreHash'])
            base, = (row['sha256'] for row in package['files'] if row['path'] == 'base-game-manifest.json')
            if core != {'format': SESSION_VERSION, 'baseGameHash': base}:
                raise ValueError('This server needs a different base game manifest.')
            self.core_hash = doc['coreHash']
        files = list(doc['files'])
        prefixes = []
        if doc['sharedHash'] is not None:
            shared = self._document(SESSION_SHARED + doc['sharedHash'], doc['sharedHash'])
            if (not isinstance(shared, dict) or shared.keys() != {'format', 'prefixes', 'files'}
                    or shared['format'] != SESSION_VERSION or not isinstance(shared['prefixes'], list)
                    or not shared['prefixes'] or any(not isinstance(prefix, str) for prefix in shared['prefixes'])):
                raise ValueError('Invalid shared map manifest.')
            prefixes = shared['prefixes']
            shared_rows = cooked_rows(shared['files'])
            if any(not name.startswith(tuple(prefixes)) for name in shared_rows):
                raise ValueError('Invalid shared map file ownership.')
            files.extend(shared_rows.values())
        return {'format': SESSION_VERSION, 'maps': {map_id: fingerprint}, 'community_maps': [map_id],
                'map_definitions': {map_id:doc['definition']} if doc['definition'] is not None else {},
                'shared_content': {prefix:[map_id] for prefix in prefixes}, 'files': files,
                'objectives': doc['objectives'], 'runtime':doc['runtime'],
                **({'minimap': minimap_payload(map_id, doc['minimap'])} if 'minimap' in doc else {})}

    def sync_map(self, map_id, fingerprint, manifest_hash=None, *, obsolete=None, notice_target=None):
        if not valid_id(map_id) or not valid_sha(fingerprint):
            raise CommunityError('The server did not provide a valid map version.')
        with self.lock:
            try:
                self.notice_target = notice_target
                self.notice_active = True
                self.status = 'Checking selected map…'
                self._check_cancelled()
                if obsolete and obsolete():
                    raise CommunityError('The lobby selected another map.')
                if manifest_hash is None:
                    metadata = next((row for row in self.map_index() if row['id'] == map_id), None)
                    if metadata is None or metadata['contentHash'] != fingerprint:
                        raise ValueError('The selected map changed. Refresh the server list and try again.')
                    manifest_hash = metadata['manifestHash']
                if not valid_sha(manifest_hash):
                    raise ValueError('Invalid map manifest hash.')
                package = json.loads((self.package / 'package-manifest.json').read_bytes())
                receipt = self._receipt(map_id)
                raw = None
                if receipt and receipt['manifestHash'] == manifest_hash:
                    try:
                        raw, (rows, sources, catalog, _) = self._cached_session(receipt['revision'], package)
                    except (OSError, ValueError, TypeError, KeyError):
                        pass
                    if raw is not None and catalog != {map_id: fingerprint}:
                        raw = None
                if raw is None:
                    remote = self._session_document(map_id, fingerprint, manifest_hash, package)
                    rows, sources, _, _ = overlay(package, remote)
                    raw = encode(remote)
                    if len(raw) > MAX_MANIFEST:
                        raise ValueError('The combined map manifest exceeds its size limit.')
                revision = sha256_bytes(raw)
                image = json.loads(raw).get('minimap', {}).get('image')
                self._cache_revision(rows, sources, revision, raw, session=True, obsolete=obsolete,
                                     optional_path=image['path'] if image is not None else None)
                self._store(self.session_path(f'map-{map_id}.json'),
                            encode({'revision': revision, 'manifestHash': manifest_hash}))
                self.local_version += 1
                self.status = 'Map ready.'
                return revision
            except (OSError, ValueError, TypeError, KeyError, EOFError, http.client.HTTPException, zlib.error) as exc:
                self.status = 'Map check paused. ' + str(exc)
                raise CommunityError('Map update failed. ' + str(exc)) from exc
            except CommunityError as exc:
                self.status = 'Map check paused. ' + str(exc)
                raise
            finally:
                self.notice_active = False
                self.progress = None

    def prefetch(self, target):
        """Keep only the latest lobby selection when members switch maps."""
        with self.prefetch_lock:
            self.prefetch_target = target
            if target is not None and (self.prefetch_thread is None or not self.prefetch_thread.is_alive()):
                self.prefetch_thread = threading.Thread(target=self._prefetch_loop, name='lobby-map-sync', daemon=True)
                self.prefetch_thread.start()

    def _prefetch_loop(self):
        while True:
            with self.prefetch_lock:
                target = self.prefetch_target
                if target is None:
                    self.prefetch_thread = None
                    return
            try:
                self.sync_map(*target, obsolete=lambda: self.prefetch_target != target, notice_target=target)
            except CommunityError:
                pass  # Joining rechecks this exact map and surfaces an actionable failure.
            with self.prefetch_lock:
                if self.prefetch_target == target:
                    self.prefetch_target = None

    def local_maps(self, index):
        # Receipts and assets are written atomically. Concurrent removal is
        # treated as a cache miss until the next local status refresh.
        package = json.loads((self.package / 'package-manifest.json').read_bytes())
        bundled_groups = None
        result = []
        for row in index:
            receipt = self._receipt(row['id'])
            state, removable = 'Not downloaded', False
            if receipt:
                removable = True
                try:
                    raw, (rows, sources, _, _) = self._cached_session(receipt['revision'], package)
                    image = json.loads(raw).get('minimap', {}).get('image')
                    for name, item in rows.items():
                        if item == image:
                            continue
                        path = (self.session_path(item['sha256'] + '.asset') if sources[name] is None
                                else self.package / sources[name])
                        if not self._matches(path, item['bytes'], item['sha256']):
                            raise ValueError('Missing cached map file.')
                    state = ('Downloaded' if receipt['manifestHash'] == row['manifestHash']
                             else 'Update available')
                except (OSError, ValueError, TypeError, KeyError):
                    pass
            elif not row['hasObjectives'] and not row.get('hasMinimap') and self.bundled_catalog().get(row['id']) == row['contentHash']:
                if bundled_groups is None:
                    _, bundled_groups = map_groups(package)
                if all(self._matches(self.package / path, size, sha)
                       for path, (size, sha) in bundled_groups[row['id']].items()
                       if path.startswith('content/')):
                    state = 'Downloaded'
            result.append(dict(row, state=state, removable=removable))
        return result

    @staticmethod
    def _matches(path, length, sha):
        try:
            return (path.resolve() == path and path.is_file()
                    and path.stat().st_size == length and digest(path) == sha)
        except OSError:
            return False

    def remove_map(self, map_id):
        if not valid_id(map_id):
            raise ValueError('Invalid map identity.')
        with self.lock:
            root = self.session_path(f'map-{map_id}.json').parent
            removed = set()
            retained = set()
            selected = []
            for path in root.glob('*.json'):
                if not valid_sha(path.stem):
                    continue
                with self.session_path(path.name).open('rb') as stream:
                    raw = bounded_read(stream)
                if sha256_bytes(raw) != path.stem:
                    raise ValueError('A cached map manifest changed. Download it again before removing map files.')
                doc = json.loads(raw)
                assets = {row['sha256'] for row in doc['files'] + doc['objectives'] if valid_sha(row['sha256'])}
                if 'minimap' in doc:
                    image = minimap_payload(next(iter(doc['maps'])), doc['minimap'])['image']
                    if image is not None:
                        assets.add(image['sha256'])
                if map_id in doc['maps']:
                    selected.append(path)
                    removed.update(assets)
                else:
                    retained.update(assets)
            self.session_path(f'map-{map_id}.json').unlink(missing_ok=True)
            for path in selected:
                path.unlink(missing_ok=True)
            for sha in removed - retained:
                self.session_path(sha + '.asset').unlink(missing_ok=True)
            self.local_version += 1

    def refresh(self, *, required=None, recheck=False):
        with self.lock:
            if required and not recheck and self.current[1].get(required[0]) == required[1]:
                return self.current
            self._check_cancelled()
            self.notice_target = None
            self.notice_active = True
            self.status = 'Checking for map updates...'
            try:
                return self._refresh(required)
            except (OSError, EOFError, ValueError, TypeError, KeyError, http.client.HTTPException, zlib.error) as exc:
                self.status = 'Map check paused. ' + str(exc)
                raise CommunityError('Map update failed. ' + str(exc)) from exc
            except CommunityError as exc:
                self.status = 'Map check paused. ' + str(exc)
                raise
            finally:
                self.notice_active = False
                self.progress = None

    def _refresh(self, required):
        package = json.loads((self.package / 'package-manifest.json').read_bytes())
        remote = self._inventory()
        rows, sources, catalog, _ = overlay(package, remote)
        if required and catalog.get(required[0]) != required[1]:
            raise CommunityError('The server map version changed. Refresh the lobby and try again.')
        if 'objectives' not in remote and catalog == self.bundled_catalog():
            self.current = (None, catalog)
        else:
            raw = encode(remote)
            revision = hashlib.sha256(raw).hexdigest()
            if self.current[0] != revision:
                self._cache_revision(rows, sources, revision, raw)
            self.current = (revision, catalog)
        self.status = 'Maps up to date.'
        return self.current

    def _cache_revision(self, rows, sources, revision, raw, *, session=False, obsolete=None, optional_path=None):
        def check():
            self._check_cancelled()
            if obsolete and obsolete():
                raise CommunityError('The lobby selected another map.')

        needed = {row['sha256']: row for name, row in rows.items()
                  if sources[name] is None and name != optional_path}
        if optional_path is not None:
            optional = rows[optional_path]
            needed.setdefault(optional['sha256'], optional)
        manifest_path = cache_path(self.workspace, revision + '.json', session=session)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        pending = []
        for checked, (sha, row) in enumerate(needed.items(), 1):
            check()
            path = cache_path(self.workspace, sha + '.asset', session=session)
            if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != sha:
                pending.append((row, path))
            if session:
                self.progress = (checked, len(needed))
        total = len(pending)
        if pending:
            options = {'check': check} if obsolete is not None else {}
            with shared_map_zip(self.package) as archive:
                remaining = sum(row['bytes'] for row, _ in pending if row['path'] != optional_path)
                for number, (row, path) in enumerate(pending, 1):
                    check()
                    self.progress = (number - 1, total)
                    self.status = (f'Syncing map files ({number:,}/{total:,})…' if session
                                   else f'Downloading map updates ({number:,}/{total:,} files)...')
                    linked = False
                    previous = cache_path(self.workspace, row['sha256'] + '.asset') if session else None
                    reusable = (previous is not None and previous.is_file()
                                and previous.stat().st_size == row['bytes'] and digest(previous) == row['sha256'])
                    if reusable and not path.exists():
                        try:
                            os.link(previous, path)
                            linked = True
                        except OSError:
                            pass
                    if row['path'] == optional_path:
                        try:
                            if not linked and shutil.disk_usage(manifest_path.parent).free >= DISK_RESERVE_BYTES + row['bytes']:
                                if archive is None or not self._import_archive_asset(archive, row, path, **options):
                                    self._download(row, path, **options)
                        except (OSError, ValueError, EOFError, http.client.HTTPException, zlib.error, CommunityError):
                            check()
                        continue
                    if not linked:
                        if shutil.disk_usage(manifest_path.parent).free < DISK_RESERVE_BYTES + remaining:
                            raise CommunityError('Free up space on the game workspace drive to download map updates.')
                        if reusable:
                            with previous.open('rb') as incoming:
                                self._write_asset(incoming, path, row['sha256'], row['bytes'], **options)
                        elif archive is None or not self._import_archive_asset(archive, row, path, **options):
                            self._download(row, path, **options)
                    remaining -= row['bytes']
                    self.progress = (number, total)
        check()
        self._store(manifest_path, raw)

    @staticmethod
    def _store(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(raw)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
