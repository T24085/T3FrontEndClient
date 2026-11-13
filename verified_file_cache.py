"""Bounded SHA256 reuse with fresh native file-identity guards.

This is a performance cache of observed bytes, never an authority/manifest cache.
Callers still compare the digest with their current expected digest and perform
their own inventory, containment and link checks. The default cache is process
local. Client preparers can opt into 24-hour receipts for immutable bulk files;
runtime code always hashes afresh in a new process. This does not protect against
a privileged metadata-forging writer; the original identity cache has the same
limitation.
"""
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
import time
import atexit


def identity(path):
    s = path.stat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError('Digest input is not a regular file: ' + str(path))
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


class VerifiedFileCache:
    def __init__(self, *, max_entries=10000, max_age_seconds=86400, clock=time.monotonic):
        if type(max_entries) is not int or not 1 <= max_entries <= 10000:
            raise ValueError('Invalid digest cache entry bound.')
        if not 0 < max_age_seconds <= 86400:
            raise ValueError('Invalid digest cache lifetime.')
        self.max_entries, self.max_age_seconds, self.clock = max_entries, max_age_seconds, clock
        self._entries, self._lock = OrderedDict(), threading.RLock()
        self.hits = self.bytes_hashed = self.files_hashed = 0
        self.receipts = None
        self.receipt_hits = 0

    def digest(self, value, *, force=False):
        path = Path(value).resolve(strict=True)
        # The resolved path remains in the key: another hardlink is not proof of
        # the caller-selected source path. stat follows resolve, on every use.
        key = str(path)
        with self._lock:
            before = identity(path)
            now = self.clock()
            old = self._entries.get(key)
            if not force and old is None and self.receipts is not None:
                retained = self.receipts.get(path, before, max_age=self.max_age_seconds)
                if retained is not None:
                    old = (before, retained[0], now - retained[1])
                    self._entries[key] = old
                    self.receipt_hits += 1
            if (not force and old is not None and old[0] == before
                    and 0 <= now - old[2] < self.max_age_seconds):
                if identity(path) != before:
                    self._entries.pop(key, None)
                    raise ValueError('File changed during cached digest verification: ' + key)
                self._entries.move_to_end(key)
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
                self.hits += 1
                return old[1]
            self._entries.pop(key, None)
            with path.open('rb') as stream:
                # Verify the open handle too; a path replacement between stat
                # and open must never publish a digest for the prior identity.
                opened = os.fstat(stream.fileno())
                # Windows Python's fstat and stat can expose different ctime
                # semantics for a newly written file. Device/file ID, size and
                # mtime establish the opened handle identity; the full five-part
                # *path stat* identity is still checked before/after and cached.
                opened_id = (opened.st_dev, opened.st_ino, opened.st_size,
                             opened.st_mtime_ns)
                if opened_id != before[:4]:
                    raise ValueError('File changed before hashing: ' + key)
                result = hashlib.file_digest(stream, 'sha256').hexdigest()
            if identity(path) != before:
                raise ValueError('File changed while hashing: ' + key)
            self._entries[key] = (before, result, self.clock())
            if self.receipts is not None:
                self.receipts.put(path, before, result)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            self.files_hashed += 1
            self.bytes_hashed += before[2]
            return result

    def snapshot(self):
        with self._lock:
            return {'entries': len(self._entries), 'cache_hits': self.hits,
                    'files_hashed': self.files_hashed, 'bytes_hashed': self.bytes_hashed,
                    'retained_bulk_hits': self.receipt_hits,
                    'scope': 'SHA256 reuse with fresh file identity guards; optional 24-hour immutable bulk receipts'}


_PROCESS_CACHE = VerifiedFileCache()


def enable_bulk_receipts(package, workspace):
    """Opt in for a preparer; cache failures never disable byte verification."""
    from bulk_verification_receipts import BulkReceipts
    try:
        store = BulkReceipts(package, workspace)
    except (OSError, ValueError):
        return False
    _PROCESS_CACHE.receipts = store
    def flush():
        try:
            store.flush()
        except (OSError, ValueError):
            pass  # Optional acceleration only; next run hashes the bytes again.
    atexit.register(flush)
    return True


def digest(path, *, force=False):
    return _PROCESS_CACHE.digest(path, force=force)


def metrics():
    return _PROCESS_CACHE.snapshot()


def verify_package(root, *, force=False, merge_manifest=None):
    """Verify every current manifest member; reuse only this process's hashes.

    Callers' content census/ownership checks remain separate. Manifest bytes are
    always read fresh, bounded and checked again at the end of the operation.
    """
    root = Path(root).resolve(strict=True)
    manifest_path = root / 'package-manifest.json'
    before = identity(manifest_path)
    with manifest_path.open('rb') as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024 or identity(manifest_path) != before:
        raise ValueError('Package manifest is too large or changed while reading.')
    result = json.loads(raw)
    if merge_manifest is not None and isinstance(result, dict):
        result = merge_manifest(root, result)
    items = result.get('files') if isinstance(result, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 10000:
        raise ValueError('Invalid package inventory.')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('Invalid package inventory entry.')
        name = item['path']
        rel = PurePosixPath(name)
        if (not rel.parts or rel.as_posix() != name or rel.is_absolute()
                or '..' in rel.parts or ':' in name or '\\' in name
                or name.casefold() in seen):
            raise ValueError('Unsafe or duplicate package path.')
        seen.add(name.casefold())
        size, expected = item.get('bytes'), item.get('sha256')
        if (type(size) is not int or size < 0 or not isinstance(expected, str)
                or re.fullmatch('[0-9a-f]{64}', expected) is None):
            raise ValueError('Invalid package member digest.')
        path = root.joinpath(*rel.parts).resolve(strict=True)
        if root not in path.parents or identity(path)[2] != size:
            raise ValueError('Missing, escaped or changed package file: ' + name)
        if digest(path, force=force) != expected:
            raise ValueError('Package file failed verification: ' + name)
    with manifest_path.open('rb') as stream:
        current_raw = stream.read(2 * 1024 * 1024 + 1)
    if identity(manifest_path) != before or current_raw != raw:
        raise ValueError('Package manifest changed while verifying members.')
    if merge_manifest is not None and merge_manifest(root, json.loads(raw)) != result:
        raise ValueError('Map inventory changed while verifying members.')
    return result
