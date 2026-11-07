"""Wire inventory and fingerprint rules for cooked community-map downloads."""
import hashlib
import json
import re

from community_maps import BY_ID, declared_maps, declared_shared_content

VERSION = 1
MANIFEST_ROUTE = '/api/map-files-v1'
FILE_ROUTE = MANIFEST_ROUTE + '/'
MAX_MANIFEST = 2 * 1024**2
MAX_FILE = 256 * 1024**2
MAX_TOTAL = 8 * 1024**3
CHUNK = 128 * 1024
SHA = re.compile('[0-9a-f]{64}')
COOKED_PATH = re.compile(
    r'content/(?:Maps/)?Community/(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.(?:umap|uasset|uexp|ubulk|uptnl)')
RESERVED = re.compile(r'CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9]', re.I)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def cooked_rows(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ValueError('Invalid cooked map file count.')
    result = {}
    seen = set()
    sizes = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'path', 'bytes', 'sha256'}:
            raise ValueError('Invalid cooked map file entry.')
        name, size, sha = row['path'], row['bytes'], row['sha256']
        if (not isinstance(name, str) or len(name) > 240 or not COOKED_PATH.fullmatch(name)
                or any(RESERVED.fullmatch(part.split('.')[0]) for part in name.split('/'))
                or name.casefold() in seen or type(size) is not int or not 0 <= size <= MAX_FILE
                or not isinstance(sha, str) or not SHA.fullmatch(sha) or sizes.setdefault(sha, size) != size):
            raise ValueError('Invalid or duplicate cooked map file.')
        result[name] = row
        seen.add(name.casefold())
    if sum(row['bytes'] for row in rows) > MAX_TOTAL:
        raise ValueError('Cooked map inventory exceeds its size limit.')
    return result


def map_catalog(manifest):
    """Fingerprint inventory metadata in the same format as verified_catalog."""
    maps = declared_maps(manifest)
    shared = declared_shared_content(manifest)
    runtime = manifest['map_runtime']
    if set(runtime) != set(maps):
        raise ValueError('Runtime ownership differs from selected maps.')
    groups = {name: {} for name in maps}
    base = None
    for row in manifest['files']:
        name = row['path']
        owners = {owner for prefix, names in shared.items() if name.startswith(prefix) for owner in names}
        for map_id in maps:
            definition = BY_ID[map_id]
            level = f'content/Maps/Community/{definition.asset_group}/{definition.level}.'
            assets = f'content/Community/{definition.asset_group}/'
            common = f'content/Community/{definition.shared_group}/'
            if (name.startswith((level, assets)) or (definition.shared_group and name.startswith(common))
                    or name in runtime[map_id]):
                owners.add(map_id)
        if name.startswith('content/') and not owners:
            raise ValueError('Unowned content: ' + name)
        if name == 'base-game-manifest.json':
            base = row['sha256']
        for owner in owners:
            groups[owner][name] = (row['bytes'], row['sha256'])
    if base is None:
        raise ValueError('Base-game fingerprint missing.')
    result = {}
    for map_id, files in groups.items():
        definition = BY_ID[map_id]
        if definition.native:
            if not runtime[map_id]:
                raise ValueError('Native runtime missing: ' + map_id)
        else:
            level = f'content/Maps/Community/{definition.asset_group}/{definition.level}'
            if any(level + suffix not in files for suffix in ('.umap', '.uexp')):
                raise ValueError('Incomplete custom map: ' + map_id)
        payload = {'format': 1, 'map': map_id, 'base_manifest_sha256': base,
                   'files': [[name, size, sha] for name, (size, sha) in sorted(files.items())]}
        result[map_id] = hashlib.sha256(encode(payload)).hexdigest()
    return result
