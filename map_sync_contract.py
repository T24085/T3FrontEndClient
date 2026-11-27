"""Wire inventory and fingerprint rules for cooked community-map downloads."""
import hashlib
import json
import re

from community_maps import MAX_MAPS, declared_definitions, declared_shared_content, valid_id, valid_label
from verified_file_cache import MAX_PACKAGE_FILES, MAX_PACKAGE_MANIFEST_BYTES

VERSION = 1
MANIFEST_ROUTE = '/api/map-files-v1'
FILE_ROUTE = MANIFEST_ROUTE + '/'
MAP_ARCHIVE_NAME = 'Clan Wars Maps.zip'
MAP_ARCHIVE_ASSETS = 'map-downloads/'
CATALOG_VERSION = 2
CATALOG_HEADER = 'X-T3-Map-Catalog'
LIVE_ROSTER_HEADER = 'X-T3-Live-Roster'
OBJECTIVES_HEADER = 'X-T3-Map-Objectives'
CATALOG_ROUTE = '/api/map-files-v2'
SESSION_VERSION = 3
SESSION_HEADER = 'X-T3-Map-Sessions'
SESSION_INDEX = '/api/maps-v3'
SESSION_MAP = SESSION_INDEX + '/map/'
SESSION_SHARED = SESSION_INDEX + '/shared/'
SESSION_CORE = SESSION_INDEX + '/core'
MAX_MANIFEST = MAX_PACKAGE_MANIFEST_BYTES
MAX_FILE = 256 * 1024**2
MAX_TOTAL = 16 * 1024**3
CHUNK = 128 * 1024
SHA = re.compile('[0-9a-f]{64}')
COOKED_PATH = re.compile(
    r'content/(?:Maps/)?Community/(?:[A-Za-z0-9_-]+/)+[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.(?:umap|uasset|uexp|ubulk|uptnl)')
RESERVED = re.compile(r'CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9]', re.I)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def valid_sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


MINIMAP_HEADER = 'X-T3-Map-Minimap'
MINIMAP_VERSION = '1'
MINIMAP_MAX_IMAGE = 16 * 1024**2
MINIMAP_MAX_DIMENSION = 4096
MINIMAP_PATH = re.compile(r'(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.png')


def minimap_settings(value):
    """Normalize the optional data-only framing from a portable map."""
    if not isinstance(value, dict) or value.keys() - {
            'center', 'scale', 'extent', 'rotation_deg', 'zoom', 'image', 'image_bounds', 'frame'}:
        raise ValueError('Invalid map minimap settings.')

    def number(value, low, high):
        if type(value) not in (int, float) or not low <= value <= high:
            raise ValueError('Invalid numeric minimap setting.')
        return value

    def pair(values, low, high):
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError('A minimap coordinate must contain X and Y.')
        return [number(value, low, high) for value in values]

    result = dict(value)
    if 'center' in result:
        result['center'] = pair(result['center'], -10_000_000, 10_000_000)
    if 'extent' in result:
        result['extent'] = pair(result['extent'], 100, 10_000_000)
    if 'scale' in result:
        result['scale'] = number(result['scale'], 0.1, 10)
    if 'rotation_deg' in result:
        result['rotation_deg'] = number(result['rotation_deg'], -360, 360)
    if 'frame' in result:
        frame = result['frame']
        if not isinstance(frame, dict) or frame.keys() != {'width', 'height'}:
            raise ValueError('A minimap frame requires width and height.')
        result['frame'] = {key: number(frame[key], 64, 1024) for key in ('width', 'height')}
    if 'zoom' in result:
        zoom = result['zoom']
        if not isinstance(zoom, dict) or not zoom or zoom.keys() - {'min', 'max', 'default'}:
            raise ValueError('Invalid minimap zoom settings.')
        result['zoom'] = {key: number(zoom[key], 0.05, 32) for key in zoom}
        low, high = zoom.get('min', 0.05), zoom.get('max', 32)
        if low > high or 'default' in zoom and not low <= zoom['default'] <= high:
            raise ValueError('Minimap default zoom must be between its limits.')
    if 'image' in result:
        path = result['image']
        if (not isinstance(path, str) or len(path) > 160 or not MINIMAP_PATH.fullmatch(path)
                or any(RESERVED.fullmatch(part.split('.')[0]) for part in path.split('/'))):
            raise ValueError('Minimap image must be a relative PNG path within the map folder.')
    if 'image_bounds' in result:
        bounds = result['image_bounds']
        if 'image' not in result or not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError('Minimap image bounds require a PNG and two corners.')
        lo, hi = (pair(corner, -10_000_000, 10_000_000) for corner in bounds)
        if any(a >= b for a, b in zip(lo, hi)):
            raise ValueError('Minimap image upper bounds must exceed lower bounds.')
        result['image_bounds'] = [lo, hi]
    return result


def minimap_payload(map_id, value):
    if (not valid_id(map_id) or not isinstance(value, dict) or value.keys() != {'settings', 'image'}):
        raise ValueError('Invalid minimap manifest entry.')
    settings = minimap_settings(value['settings'])
    image = value['image']
    if image is not None and (
            'image' not in settings or not isinstance(image, dict) or image.keys() != {'path', 'sha256', 'bytes'}
            or image['path'] != f"lua/{map_id}/{settings['image']}" or not valid_sha(image['sha256'])
            or type(image['bytes']) is not int or not 33 <= image['bytes'] <= MINIMAP_MAX_IMAGE):
        raise ValueError('Invalid minimap image inventory entry.')
    return {'settings': settings, 'image': image}


def png_dimensions(header):
    """Accept only bounded PNG images before handing bytes to the native importer."""
    if len(header) < 33 or header[:16] != bytes.fromhex('89504e470d0a1a0a0000000d49484452'):
        raise ValueError('Minimap graphic does not contain a PNG header.')
    width = int.from_bytes(header[16:20], 'big')
    height = int.from_bytes(header[20:24], 'big')
    if not 1 <= width <= MINIMAP_MAX_DIMENSION or not 1 <= height <= MINIMAP_MAX_DIMENSION:
        raise ValueError('Minimap PNG dimensions exceed the supported range.')
    return width, height


def session_index(value):
    if (not isinstance(value, dict) or value.keys() != {'format', 'maps', 'coreHash'}
            or value['format'] != SESSION_VERSION or not valid_sha(value['coreHash'])
            or not isinstance(value['maps'], list) or not 1 <= len(value['maps']) <= MAX_MAPS):
        raise ValueError('Invalid map index.')
    result = {}
    for row in value['maps']:
        fields = {'id', 'label', 'gameTag', 'bytes', 'fileCount', 'contentHash', 'manifestHash', 'hasObjectives'}
        if (not isinstance(row, dict) or not fields <= row.keys() <= fields | {'hasMinimap'}
                or 'hasMinimap' in row and not isinstance(row['hasMinimap'], bool)
                or not valid_id(row['id']) or row['id'].casefold() in result
                or not valid_label(row['label']) or row['gameTag'] not in ('T1', 'T2', 'T3', 'Community')
                or type(row['bytes']) is not int or not 0 <= row['bytes'] <= MAX_TOTAL + 256 * 1024 + MINIMAP_MAX_IMAGE
                or type(row['fileCount']) is not int or not 0 <= row['fileCount'] <= MAX_PACKAGE_FILES + 2
                or not valid_sha(row['contentHash']) or not valid_sha(row['manifestHash'])
                or type(row['hasObjectives']) is not bool):
            raise ValueError('Invalid map index entry.')
        result[row['id'].casefold()] = row
    return sorted(result.values(), key=lambda row: (row['label'].casefold(), row['id']))


def cooked_rows(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PACKAGE_FILES:
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


def map_objective_rows(rows, definitions):
    """Accept only bounded objectives.lua entries for declared community maps."""
    paths = {f'lua/{key}/objectives.lua' for key, definition in definitions.items() if not definition.native}
    if not isinstance(rows, list) or len(rows) > len(paths):
        raise ValueError('Invalid map objectives inventory.')
    result = {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'path', 'bytes', 'sha256'}
                or not isinstance(row['path'], str) or row['path'] not in paths or row['path'] in result
                or type(row['bytes']) is not int or not 0 < row['bytes'] <= 256 * 1024
                or not isinstance(row['sha256'], str) or not SHA.fullmatch(row['sha256'])):
            raise ValueError('Invalid map objectives file.')
        result[row['path']] = row
    return result


def map_groups(manifest):
    """Resolve the files each map needs from its package inventory."""
    definitions = declared_definitions(manifest)
    maps = tuple(definitions)
    shared = declared_shared_content(manifest, definitions)
    runtime = manifest['map_runtime']
    if set(runtime) != set(maps):
        raise ValueError('Runtime ownership differs from selected maps.')
    groups = {name: {} for name in maps}
    base = None
    for row in manifest['files']:
        name = row['path']
        owners = {owner for prefix, names in shared.items() if name.startswith(prefix) for owner in names}
        for map_id in maps:
            definition = definitions[map_id]
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
    for map_id, files in groups.items():
        definition = definitions[map_id]
        if definition.native:
            if not runtime[map_id]:
                raise ValueError('Native runtime missing: ' + map_id)
        else:
            level = f'content/Maps/Community/{definition.asset_group}/{definition.level}'
            if any(level + suffix not in files for suffix in ('.umap', '.uexp')):
                raise ValueError('Incomplete custom map: ' + map_id)
            prefix = f'content/Community/{definition.asset_group}/'
            if not any(name.startswith(prefix) for name in files):
                raise ValueError('Map assets are missing: ' + map_id)
    return base, groups


def map_catalog(manifest):
    """Fingerprint inventory metadata in the same format as verified_catalog."""
    base, groups = map_groups(manifest)
    result = {}
    for map_id, files in groups.items():
        payload = {'format': 1, 'map': map_id, 'base_manifest_sha256': base,
                   'files': [[name, size, sha] for name, (size, sha) in sorted(files.items())]}
        result[map_id] = hashlib.sha256(encode(payload)).hexdigest()
    return result
