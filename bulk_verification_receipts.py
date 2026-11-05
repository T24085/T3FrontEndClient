"""Bounded, optional retained hashes for immutable bulk assets only.

Like the original game's existing 24-hour identity cache, these receipts are a
performance hint, not authentication against a privileged metadata-forging user.
Every consumer still compares the digest to its current manifest. Executables,
scripts, manifests, settings and runtime DLLs never qualify for retention.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

LIMIT = 8 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_AGE = 86400


class BulkReceipts:
    def __init__(self, package, workspace, *, clock=time.time):
        self.content = Path(package).resolve(strict=True) / 'content'
        self.assets = Path(workspace).resolve(strict=True) / 'asset-cache'
        self.clock = clock
        self.namespace = hashlib.sha256(str(Path(package).resolve(strict=True)).encode()).hexdigest()
        directory = Path(workspace) / 'verification-cache'
        directory.mkdir(exist_ok=True)
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            raise ValueError('Verification-cache directory must be a real directory.')
        self.path = directory / (self.namespace + '.json')
        self.records = {}
        self.writable = True
        self.pending_bytes = 0
        self.last_flush = self.clock()
        try:
            if self.path.is_symlink() or self.path.is_junction():
                raise ValueError('Linked receipt is not owned cache data.')
            with self.path.open('rb') as stream:
                raw = stream.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('Receipt exceeded its bound.')
            data = json.loads(raw)
            if (not isinstance(data, dict) or data.get('format') != 1
                    or data.get('namespace') != self.namespace
                    or not isinstance(data.get('records'), dict) or len(data['records']) > MAX_ENTRIES):
                raise ValueError('Unknown receipt format.')
            self.records = data['records']
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, RecursionError):
            # Retain unfamiliar/corrupt data. A cache miss restores normal hashing.
            self.writable = False

    def eligible(self, path):
        path = Path(path)
        if self.content in path.parents:
            return path.suffix.lower() in ('.uasset', '.umap', '.uexp', '.ubulk')
        return (path.parent.parent == self.assets and re.fullmatch('[0-9a-f]{64}\\.asset', path.name) is not None
                and path.parent.name == path.name[:2])

    def get(self, path, identity, *, max_age=MAX_AGE):
        if not self.eligible(path):
            return None
        record = self.records.get(str(path))
        if not isinstance(record, dict):
            return None
        stamp = record.get('verified_at')
        digest = record.get('sha256')
        now = self.clock()
        if (type(stamp) not in (int, float) or not 0 <= now - stamp < min(max_age, MAX_AGE)
                or record.get('identity') != list(identity) or not isinstance(digest, str)
                or re.fullmatch('[0-9a-f]{64}', digest) is None):
            return None
        return digest, now - stamp

    def put(self, path, identity, digest):
        if self.eligible(path):
            self.records[str(path)] = dict(identity=list(identity), sha256=digest, verified_at=self.clock())
            self.pending_bytes += identity[2]
            if self.writable and (self.pending_bytes >= 128*1024*1024 or self.clock()-self.last_flush >= 15):
                try:
                    self.flush()
                except (OSError, ValueError):
                    self.writable = False

    def flush(self):
        if not self.writable:
            return
        stamp = self.clock()
        records = {key: value for key, value in self.records.items()
                   if isinstance(value, dict) and type(value.get('verified_at')) in (int, float)
                   and 0 <= stamp - value['verified_at'] < MAX_AGE}
        records = dict(sorted(records.items(), key=lambda row: row[1]['verified_at'], reverse=True)[:MAX_ENTRIES])
        raw = (json.dumps(dict(format=1, namespace=self.namespace, records=records), separators=(',', ':')) + '\n').encode()
        if len(raw) > LIMIT:
            return
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        with temporary.open('xb') as stream:
            stream.write(raw)
        if self.path.is_symlink() or self.path.is_junction():
            raise ValueError('Receipt path became a link; temporary retained.')
        os.replace(temporary, self.path)
        self.pending_bytes = 0
        self.last_flush = self.clock()
