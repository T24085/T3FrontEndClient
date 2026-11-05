"""Immutable, verified bulk-file reuse on the destination's local NTFS volume.

Cache filenames select candidates only. Every existing cache member is verified
against the caller's current expected SHA256/size in this process. Mutable game
executables, runtime/configuration files and profiles must not use this API.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import re
import shutil
import uuid

from verified_file_cache import digest, identity


class BulkCacheError(ValueError):
    pass


DISK_RESERVE_BYTES = 2 * 1024 * 1024 * 1024


def local_filesystem(path):
    """Read native volume identity; unknown/remote filesystems are not cacheable."""
    if os.name != 'nt':
        return None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    volume = ctypes.create_unicode_buffer(32768)
    get_path = kernel.GetVolumePathNameW
    get_path.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
    get_path.restype = ctypes.c_int
    if not get_path(str(Path(path).resolve(strict=True)), volume, len(volume)):
        raise ctypes.WinError(ctypes.get_last_error())
    drive_type = kernel.GetDriveTypeW
    drive_type.argtypes, drive_type.restype = (ctypes.c_wchar_p,), ctypes.c_uint32
    if drive_type(volume.value) != 3:  # DRIVE_FIXED
        return None
    filesystem = ctypes.create_unicode_buffer(64)
    info = kernel.GetVolumeInformationW
    info.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_wchar_p, ctypes.c_uint32)
    info.restype = ctypes.c_int
    if not info(volume.value, None, 0, None, None, None, filesystem, len(filesystem)):
        raise ctypes.WinError(ctypes.get_last_error())
    return filesystem.value


def _directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    # Caller-selected workspace may have parents outside our ownership. Within
    # the cache, existing links/reparse directories never redirect publication.
    if path.is_symlink() or path.is_junction() or not path.is_dir():
        raise BulkCacheError('Bulk cache directory is a link or not a directory: ' + str(path))


def _expected(value, size):
    if (not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None
            or type(size) is not int or size < 0):
        raise BulkCacheError('Bulk staging requires a verified manifest SHA256 and size.')


class BulkStageCache:
    def __init__(self, cache_root, *, filesystem_loader=local_filesystem, emit=None):
        cache_root = Path(cache_root).absolute()
        _directory(cache_root.parent)
        self.filesystem = filesystem_loader(cache_root.parent)
        self.enabled = self.filesystem == 'NTFS'
        self.root = cache_root
        self.emit = emit or (lambda line: print(line, flush=True))
        self.counts = {'direct_hardlinks': 0, 'cache_hardlinks': 0, 'cache_published_bytes': 0,
                       'private_copied_bytes': 0, 'cache_reused_files': 0}
        if self.enabled:
            _directory(self.root)
            self.root = self.root.resolve(strict=True)
        self.emit('BULK_STAGE|' + ('cache_ntfs' if self.enabled else 'private_copy') +
                  '|filesystem=' + str(self.filesystem))

    def _verify_cached(self, target, expected, size):
        before = identity(target)
        if target.is_symlink() or target.is_junction() or before[2] != size:
            raise BulkCacheError('Shared cache entry is invalid and retained: ' + str(target))
        if digest(target) != expected:
            raise BulkCacheError('Shared cache entry digest differs and is retained: ' + str(target))
        if identity(target) != before:
            raise BulkCacheError('Shared cache changed during verification; retained: ' + str(target))
        return before

    def _copy_verified(self, src, dst, before, expected, size):
        with dst.open('xb') as output:
            owned = os.fstat(output.fileno())
            owned_id = (owned.st_dev, owned.st_ino)
        # A failed private file stays in the owned session for its existing
        # cleanup owner; shared cache cleanup below only handles our exact temp.
        self._fill_owned_file(src, dst, owned_id, before, expected, size, purpose='private_copy')
        return owned_id

    def stage(self, source, destination, *, expected_sha256, expected_bytes,
              expected_source_identity=None):
        _expected(expected_sha256, expected_bytes)
        src = Path(source).resolve(strict=True)
        dst = Path(destination).absolute()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(dst):
            raise BulkCacheError('Private staging destination already exists: ' + str(dst))
        before = identity(src)
        if expected_source_identity is None:
            # Cooked members were already checked by verify_package in this
            # process. A changed member invalidates that digest and is rehashed.
            if digest(src) != expected_sha256:
                raise BulkCacheError('Cooked source differs from verified manifest: ' + str(src))
            if identity(src) != before:
                raise BulkCacheError('Cooked source changed after verification: ' + str(src))
        elif tuple(expected_source_identity) != before:
            raise BulkCacheError('Original source changed after verification: ' + str(src))
        if before[2] != expected_bytes:
            raise BulkCacheError('Bulk source size differs from verified manifest: ' + str(src))
        if self.enabled and src.drive.casefold() == dst.drive.casefold():
            try:
                os.link(src, dst)
            except OSError as exc:
                if getattr(exc, 'winerror', None) not in (1, 5, 17, 50, 1142, 1314):
                    raise
            else:
                if identity(src) != before:
                    raise BulkCacheError('Bulk source changed during direct staging: ' + str(src))
                self.counts['direct_hardlinks'] += 1
                return 'hardlink'
        if not self.enabled:
            self._copy_verified(src, dst, before, expected_sha256, expected_bytes)
            self.counts['private_copied_bytes'] += expected_bytes
            return 'copy'
        bucket = self.root / expected_sha256[:2]
        _directory(bucket)
        target = bucket / (expected_sha256 + '.asset')
        if os.path.lexists(target):
            self._verify_cached(target, expected_sha256, expected_bytes)
            self.counts['cache_reused_files'] += 1
        else:
            temp = bucket / (expected_sha256 + '.' + uuid.uuid4().hex + '.tmp')
            temp_id = None
            try:
                # Own the pathname before writing so failure cleanup never
                # mistakes an arbitrary old file for our temporary resource.
                with temp.open('xb') as created:
                    st = os.fstat(created.fileno())
                    temp_id = (st.st_dev, st.st_ino)
                # Copy into the already-owned file, not an overwriting API.
                self._fill_owned_file(src, temp, temp_id, before, expected_sha256, expected_bytes,
                                      purpose='cache_fill')
                try:
                    if os.name == 'nt':
                        os.rename(temp, target)  # Windows: never replaces target.
                    else:
                        os.link(temp, target)  # Non-Windows test boundary, exclusive.
                        temp.unlink()
                except FileExistsError:
                    self._verify_cached(target, expected_sha256, expected_bytes)
                else:
                    self.counts['cache_published_bytes'] += expected_bytes
                self._verify_cached(target, expected_sha256, expected_bytes)
            finally:
                if temp_id is not None and os.path.lexists(temp):
                    if temp.is_symlink() or identity(temp)[:2] != temp_id:
                        raise BulkCacheError('Temporary cache identity changed; retained: ' + str(temp))
                    temp.unlink()
        if identity(src) != before:
            raise BulkCacheError('Bulk source changed before cache staging: ' + str(src))
        cache_id = self._verify_cached(target, expected_sha256, expected_bytes)
        try:
            os.link(target, dst)
        except OSError as exc:
            if getattr(exc, 'winerror', None) != 1142:  # ERROR_TOO_MANY_LINKS
                raise
            # Link capacity belongs to this one immutable cache inode. Keep
            # sharing other members; only this session gets a verified copy.
            # Neither a different error nor a changed source/cache is copy
            # authority, and the existing private-file owner remains exclusive.
            if (identity(src) != before
                    or self._verify_cached(target, expected_sha256, expected_bytes) != cache_id):
                raise BulkCacheError('Bulk source/cache changed before link-limit copy.')
            self._copy_verified(src, dst, before, expected_sha256, expected_bytes)
            if (identity(src) != before
                    or self._verify_cached(target, expected_sha256, expected_bytes) != cache_id):
                raise BulkCacheError('Bulk source/cache changed during link-limit copy.')
            self.counts['private_copied_bytes'] += expected_bytes
            self.emit('BULK_STAGE|cache_link_limit_copy|winerror=1142|bytes=' + str(expected_bytes))
            return 'copy'
        if identity(src) != before or identity(dst) != cache_id or identity(target) != cache_id:
            raise BulkCacheError('Bulk source/cache identity changed during staging.')
        self.counts['cache_hardlinks'] += 1
        if expected_bytes >= 16 * 1024 * 1024:
            self.emit('BULK_STAGE|cache_link|bytes=' + str(expected_bytes))
        return 'hardlink'

    def _fill_owned_file(self, src, temp, temp_id, before, expected, size, *, purpose):
        if identity(temp)[:2] != temp_id or identity(temp)[2] != 0:
            raise BulkCacheError('Temporary cache identity changed before copy.')
        free = shutil.disk_usage(temp.parent).free
        if free < size + DISK_RESERVE_BYTES:
            raise BulkCacheError('Insufficient staging storage: need file bytes=' + str(size) +
                                 ' plus 2 GiB reserve; free=' + str(free) + '. Choose an NTFS '
                                 'workspace on the verified original game volume for direct hardlinks.')
        hashed, count = hashlib.sha256(), 0
        report = size >= 16 * 1024 * 1024
        if report:
            self.emit('BULK_STAGE|' + purpose + '_start|bytes=' + str(size))
        next_progress = 64 * 1024 * 1024
        with temp.open('r+b') as output, src.open('rb') as stream:
            if (os.fstat(output.fileno()).st_dev, os.fstat(output.fileno()).st_ino) != temp_id:
                raise BulkCacheError('Temporary cache handle differs.')
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != before[:4]:
                raise BulkCacheError('Bulk source handle changed before cache fill.')
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                count += len(block)
                if count > size:
                    raise BulkCacheError('Bulk source grew during cache fill.')
                hashed.update(block)
                output.write(block)
                if report and count >= next_progress:
                    self.emit('BULK_STAGE|' + purpose + '_progress|copied_bytes=' + str(count) +
                              '|total_bytes=' + str(size))
                    next_progress += 64 * 1024 * 1024
            output.flush()
        if (count != size or hashed.hexdigest() != expected or identity(src) != before
                or identity(temp)[:2] != temp_id or identity(temp)[2] != size):
            raise BulkCacheError('Cache fill bytes/source identity failed verification.')
        if report:
            self.emit('BULK_STAGE|' + purpose + '_complete|bytes=' + str(size))

    def snapshot(self):
        return dict(self.counts, filesystem=self.filesystem, cache_enabled=self.enabled,
                    cache_root=str(self.root), scope='verified immutable bulk bytes; not native readiness')
