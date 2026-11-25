"""Build world-aligned terrain overviews from preserved map authoring data."""
import argparse
import hashlib
import json
from pathlib import Path


def reflected_grid(grid, tiles):
    import numpy as np
    intervals = grid.shape[0] - 1
    positions = np.arange(tiles * intervals + 1)
    tile = np.minimum(positions // intervals, tiles - 1)
    local = positions - tile * intervals
    indices = np.where(tile % 2 == 1, intervals - local, local)
    return grid[np.ix_(indices, indices)]


def terrain_image(grid, spacing, snow=False):
    import numpy as np
    from PIL import Image
    finite = np.isfinite(grid)
    low, high = np.nanmin(grid), np.nanmax(grid)
    heights = np.nan_to_num(grid, nan=float(low))
    dy, dx = np.gradient(heights, spacing)
    normal_length = np.sqrt(dx * dx + dy * dy + 1)
    light = np.clip((-.5 * dx - .65 * dy + .7) / normal_length, -.3, 1)
    shade = .75 + .28 * light
    palette = np.array([[203, 215, 194], [170, 192, 161], [196, 187, 159], [227, 224, 211]])
    if snow:
        palette = np.array([[200, 218, 230], [213, 225, 232], [230, 235, 236], [248, 248, 245]])
    fraction = np.clip((heights - low) / max(float(high - low), 1), 0, 1) * (len(palette) - 1)
    band = np.minimum(fraction.astype(int), len(palette) - 2)
    blend = (fraction - band)[..., None]
    rgb = (palette[band] * (1 - blend) + palette[band + 1] * blend) * shade[..., None]
    contours = np.floor(heights / 10)
    edge = np.zeros(heights.shape, dtype=bool)
    edge[1:, :] |= contours[1:, :] != contours[:-1, :]
    edge[:, 1:] |= contours[:, 1:] != contours[:, :-1]
    rgb[edge] *= .87
    rgba = np.dstack((np.clip(rgb, 0, 255).astype('uint8'), finite.astype('uint8') * 255))
    return Image.fromarray(rgba), [float(low), float(high)]


def build(config, source_root, expanded_root, output):
    import numpy as np
    from lupa.lua54 import LuaRuntime
    descriptor_path = Path(config['host_package']) / 'lua/community_maps.lua'
    descriptors = LuaRuntime().execute(descriptor_path.read_text(encoding='utf-8'))
    source_manifest = json.loads((source_root/'manifest.json').read_bytes())
    expanded_manifest = json.loads((expanded_root/'manifest.json').read_bytes())
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for map_id, descriptor in descriptors.items():
        if not descriptor['objectives']:
            continue
        name = descriptor['asset_group'] or descriptor['package'].split('/')[-2]
        landmarks = []
        objectives = descriptor['objectives']
        for _, flag in objectives['flags'].items():
            landmarks.append(dict(kind='flag', team=1 if flag[1] == 'TeamA' else 2,
                                  x=flag[2]/100, y=flag[3]/100, z=flag[4]/100))
        for _, start in objectives['starts'].items():
            landmarks.append(dict(kind='spawn', team=start[1], x=start[2]/100, y=start[3]/100, z=start[4]/100))
        size = descriptor['map_size_cm']
        half = size / 200 if size else None
        data = dict(map_id=map_id, label=descriptor['label'] or map_id, landmarks=landmarks,
                    bounds=dict(min_x=-half, max_x=half, min_y=-half, max_y=half) if half else None,
                    image_url=None, source='Training host map descriptor',
                    descriptor_sha256=hashlib.sha256(descriptor_path.read_bytes()).hexdigest())
        if name in source_manifest:
            expanded = descriptor['edition'] == 2026 or map_id.endswith('2026')
            path = (expanded_root/expanded_manifest[name]['height_file'] if expanded
                    else source_root/(name+'.npy'))
            expected = (expanded_manifest[name]['height_sha256'] if expanded
                        else source_manifest[name]['array_sha256'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Terrain source digest changed for ' + map_id)
            grid = np.load(path, allow_pickle=False)
            if grid.ndim != 2 or grid.shape[0] != grid.shape[1]:
                raise ValueError('Expected a square terrain heightfield')
            tiles = 5 if expanded else 1
            extent = expanded_manifest[name]['horizontal_tile_m'] if expanded else source_manifest[name]['extent_m']
            if half and abs(2*half - extent*tiles) > 1:
                raise ValueError('Terrain extent does not match the training map ' + map_id)
            half = extent * tiles / 2
            data['bounds'] = dict(min_x=-half, max_x=half, min_y=-half, max_y=half)
            full = reflected_grid(grid, tiles)
            # Source row zero maps to positive Unreal world Y after the FBX axis conversion.
            image, elevation = terrain_image(full, extent/(grid.shape[0]-1), name == 'Snowblind')
            image.save(output/(map_id+'.png'), optimize=True)
            data.update(image_url='/api/map/'+map_id+'/image', elevation_m=elevation,
                        source='Preserved source terrain heightfield and training host objectives',
                        terrain_sha256=expected, contour_interval_m=10)
        (output/(map_id+'.json')).write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
        records.append(dict(map_id=map_id, terrain=data['image_url'] is not None))
    (output/'index.json').write_text(json.dumps(records, indent=2)+'\n', encoding='utf-8')
    print(f"Built {len(records)} map overviews, {sum(row['terrain'] for row in records)} with terrain.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('source_root', type=Path)
    parser.add_argument('expanded_root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(json.loads(args.config.read_bytes()), args.source_root, args.expanded_root, args.output)
