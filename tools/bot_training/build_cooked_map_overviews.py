"""Render dashboard overviews from verified regular-grid community terrain meshes."""
import argparse
from hashlib import file_digest
import json
import mmap
from pathlib import Path
import re
import struct

from build_map_overviews import terrain_image


POSITION_BUFFER = re.compile(rb'\x0c\0\0\0(.{4})\x0c\0\0\0\1', re.DOTALL)
TILE_CELLS = 128


def sha256(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def cooked_grid(path):
    import numpy as np

    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for header in POSITION_BUFFER.finditer(data):
            count = struct.unpack('<I', header[1])[0]
            end = header.end() + count * 12
            if not 4096 <= count <= 1025 * 1025 or end > len(data):
                continue
            vertices = np.frombuffer(data[header.end():end], dtype='<f4').reshape(-1, 3)
            if not np.isfinite(vertices).all() or np.abs(vertices).max() > 2_000_000:
                continue
            low = vertices.min(axis=0)[:2].astype('float64')
            high = vertices.max(axis=0)[:2].astype('float64')
            span = high - low
            if min(span) < 10_000 or abs(span[0] - span[1]) > 1:
                continue
            sides = np.array([np.unique(np.rint(axis * 4)).size for axis in vertices[:, :2].T])
            if not all(side in (65, 129, 257, 513, 1025) for side in sides):
                continue
            capacity = sides.prod()
            if not .75 * capacity <= count <= capacity:
                continue
            step = span / (sides - 1)
            xy = np.rint((vertices[:, :2] - low) / step).astype('int32')
            if np.abs(vertices[:, :2] - (low + xy * step)).max() > .25:
                continue
            indices = xy[:, 1] * sides[0] + xy[:, 0]
            if np.unique(indices).size != count:
                continue
            heights = np.full(capacity, np.nan, dtype='float32')
            heights[indices] = vertices[:, 2]
            grid = heights.reshape(tuple(reversed(sides)))
            for axis in (0, 1):
                view = grid.swapaxes(0, axis)
                side = view.shape[0]
                if side < TILE_CELLS + 1:
                    interpolated = np.empty((TILE_CELLS + 1, view.shape[1]), dtype='float32')
                    interpolated[::2] = view
                    interpolated[1::2] = (view[:-1] + view[1:]) / 2
                    view = interpolated
                else:
                    view = view[::(side - 1) // TILE_CELLS]
                grid = view.swapaxes(0, axis)
            return low, high, grid
    raise ValueError(f'No verified regular position grid in {path.name}.')


def read_descriptor(path, row, map_id):
    from lupa.lua54 import LuaRuntime, lua_type

    vm = LuaRuntime()
    source = path.read_text(encoding='utf-8')
    payload = vm.execute(source)
    layout = re.search(r'\blocal layout\s*=\s*(\{.*?^\})', source, re.DOTALL | re.MULTILINE)
    if lua_type(payload) != 'table':
        return None, vm.execute('return ' + layout[1]) if layout else None
    package = f"/Game/Maps/Community/{row['asset_group']}/{row['level']}"
    descriptor = payload['descriptor']
    if lua_type(descriptor) == 'function':
        descriptor = descriptor(vm.table_from(dict(
            name=map_id, package=package, world=f"{package}.{row['level']}:",
            asset_group=row['asset_group'], label=row['label'])))
    descriptor = descriptor or payload
    objectives = descriptor['objectives'] or payload['layout']
    if (objectives is None or objectives['flags'] is None) and layout:
        objectives = vm.execute('return ' + layout[1])
    return descriptor['geometry'], objectives


def terrain_tiles(content, group, geometry):
    if geometry is None:
        raise ValueError('No world-space terrain placements in the map adapter.')
    assets = {}
    tiles = []
    prefix = f'/Game/Community/{group}/'
    for item in geometry.values():
        if item['kind'] != 'terrain':
            continue
        asset = item['asset']
        if not asset.startswith(prefix):
            raise ValueError('The terrain asset belongs to a different map.')
        path = Path(asset.removeprefix('/Game/').split('.')[0] + '.uexp')
        if '..' in path.parts:
            raise ValueError('Invalid terrain asset path.')
        if path not in assets:
            source = content / path
            assets[path] = (*cooked_grid(source), sha256(source))
        low, high, heights, _ = assets[path]
        x, y, z = (item['position_cm'][i] for i in (1, 2, 3))
        tiles.append((low + (x, y), high + (x, y), heights + z))
    if not tiles:
        raise ValueError('No declared terrain tiles.')
    return tiles, {path.as_posix(): data[-1] for path, data in assets.items()}


def assemble(tiles):
    import numpy as np

    low = np.min([tile[0] for tile in tiles], axis=0)
    high = np.max([tile[1] for tile in tiles], axis=0)
    span = tiles[0][1] - tiles[0][0]
    counts = np.rint((high - low) / span).astype('int32')
    if any(counts < 1) or any(counts > 8) or len(tiles) != counts.prod():
        raise ValueError('Terrain tiles do not cover a complete rectangular grid.')
    out = np.full((counts[1] * TILE_CELLS + 1, counts[0] * TILE_CELLS + 1), np.nan, dtype='float32')
    seen = set()
    for start, end, heights in tiles:
        index = np.rint((start - low) / span).astype('int32')
        x, y = map(int, index * TILE_CELLS)
        if tuple(index) in seen or np.abs(start - low - index * span).max() > .5 or np.abs(end - start - span).max() > .5:
            raise ValueError('Terrain tile placement did not match its neighbors.')
        seen.add(tuple(index))
        area = out[y:y + TILE_CELLS + 1, x:x + TILE_CELLS + 1]
        measured = np.isfinite(heights)
        overlap = np.isfinite(area) & measured
        if overlap.any() and np.abs(area[overlap] - heights[overlap]).max() > 10:
            raise ValueError('Terrain elevations disagreed along a tile edge.')
        np.copyto(area, heights, where=measured)
    if len(seen) != counts.prod() or np.isfinite(out).mean() < .9:
        raise ValueError('Terrain image has incomplete coverage.')
    return out[::-1] / 100, low / 100, high / 100, float(span[0] / TILE_CELLS / 100)


def landmarks_for(layout):
    if layout is None or layout['flags'] is None or layout['starts'] is None:
        return []
    landmarks = [dict(kind='flag', team=1 if flag[1] == 'TeamA' else 2,
                      x=flag[2]/100, y=flag[3]/100, z=flag[4]/100)
                 for flag in layout['flags'].values()]
    landmarks.extend(dict(kind='spawn', team=start[1], x=start[2]/100, y=start[3]/100, z=start[4]/100)
                     for start in layout['starts'].values())
    return landmarks


def write_overview(output, map_id, label, surface, landmarks, provenance, *, snow=False):
    grid, low, high, spacing = surface
    bounds = dict(min_x=float(low[0]), max_x=float(high[0]), min_y=float(low[1]), max_y=float(high[1]))
    for point in landmarks:
        if not (bounds['min_x'] <= point['x'] <= bounds['max_x']
                and bounds['min_y'] <= point['y'] <= bounds['max_y']):
            raise ValueError(f'{map_id}: an objective is outside the rendered terrain.')
    image, elevation = terrain_image(grid, spacing, snow)
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / (map_id + '.png'), optimize=True)
    metadata = dict(map_id=map_id, label=label, bounds=bounds, landmarks=landmarks,
                    image_url=f'/api/map/{map_id}/image', elevation_m=elevation,
                    source='World-aligned elevations from the shipped map terrain', **provenance)
    (output / (map_id + '.json')).write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')


def build(config, output, ids):
    manifest = json.loads(Path(config['map_catalog']).read_bytes())
    content = Path(config['cached_client_session']) / 'game/Topaz/Content'
    adapters = Path(config['host_package']) / 'lua'
    for map_id in ids:
        row = manifest['map_definitions'][map_id]
        adapter = adapters / map_id / 'objectives.lua'
        geometry, layout = read_descriptor(adapter, row, map_id)
        tiles, hashes = terrain_tiles(content, row['asset_group'], geometry)
        provenance = dict(map_fingerprint=manifest['map_fingerprints'][map_id],
                          descriptor_sha256=sha256(adapter), terrain_sha256=hashes)
        write_overview(output, map_id, row['label'], assemble(tiles), landmarks_for(layout), provenance,
                       snow=map_id == 'KatabaticT22026')
        print(f'Built {map_id} from {len(tiles)} world-positioned tiles.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('maps', nargs='+')
    args = parser.parse_args()
    build(json.loads(args.config.read_bytes()), args.output, args.maps)
