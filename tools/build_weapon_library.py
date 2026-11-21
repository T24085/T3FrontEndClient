"""Build a private Starter weapon library from verified local Unreal exports."""
import argparse
from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import struct
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image


CONTENT = 'Topaz/Content/'
VIEWS = {'1p': 'First person', '3p': 'Third person'}
MESH = re.compile(r'^(SK_|SKM_|SM_|MESH_)', re.I)
SOCKET_FIELDS = {'SocketName', 'BoneName', 'RelativeLocation', 'RelativeRotation', 'RelativeScale'}
COLOR_PARAMETERS = {'albedo', 'albedotexture', 'basecolor', 'basecolormap', 'basecolortexture',
                    'dif', 'diffuse', 'diffusemap', 'diffusetexture', 'colormap'}


def read_json(path):
    return json.loads(path.read_bytes())


def asset_path(raw):
    return ('/Game/' + raw[len(CONTENT):]).removesuffix('.uasset')


def asset_view(package):
    return next((VIEWS[part.casefold()] for part in PurePosixPath(package).parts
                 if part.casefold() in VIEWS), 'Shared')


def display_family(family):
    compact = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', family.replace('_', ' '))
    return re.sub(r'Spin\s*[Ff]usor', 'Spinfusor', compact)


def model_label(mesh):
    name = re.sub(r'^(SK_|SKL_|SKM_|SM_|MESH_)(WEP_)?', '', mesh, flags=re.I)
    name = re.sub(r'_?[13]p$', '', name, flags=re.I)
    return display_family(name)


def glb_parts(raw):
    magic, version, length, json_size, tag = struct.unpack_from('<4sIII4s', raw)
    if (magic, version, length, tag) != (b'glTF', 2, len(raw), b'JSON'):
        raise ValueError('Expected a GLB 2.0 mesh.')
    doc = json.loads(raw[20:20+json_size])
    binary_size, tag = struct.unpack_from('<I4s', raw, 20+json_size)
    binary = memoryview(raw)[28+json_size:]
    if tag != b'BIN\0' or len(binary) != binary_size:
        raise ValueError('Missing embedded GLB geometry.')
    return doc, binary


def accessor(doc, binary, index):
    row = doc['accessors'][index]
    view = doc['bufferViews'][row['bufferView']]
    dtype = np.dtype({5121: 'u1', 5123: '<u2', 5125: '<u4', 5126: '<f4'}[row['componentType']])
    width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}[row['type']]
    start = view.get('byteOffset', 0)
    stride = view.get('byteStride', width*dtype.itemsize)
    offset, count = row.get('byteOffset', 0), row['count']
    if ('sparse' in row or view['buffer'] != 0 or count < 1 or start < 0 or offset < 0
            or stride < width*dtype.itemsize
            or offset+(count-1)*stride+width*dtype.itemsize > view['byteLength']
            or start+view['byteLength'] > len(binary)):
        raise ValueError('Invalid GLB accessor.')
    return np.ndarray((count, width), dtype=dtype, buffer=binary, offset=start+offset,
                      strides=(stride, dtype.itemsize))


def preview_model(raw, texture_for):
    doc, binary = glb_parts(raw)
    if len(doc['meshes']) != 1:
        raise ValueError('The preview needs an individual weapon mesh.')
    parts, textures = [], {}
    for primitive in doc['meshes'][0]['primitives']:
        if primitive.get('mode', 4) != 4:
            raise ValueError('Expected triangles in the weapon mesh.')
        attributes = primitive['attributes']
        indices = accessor(doc, binary, primitive['indices']).ravel()
        positions = accessor(doc, binary, attributes['POSITION'])[indices]
        normals = accessor(doc, binary, attributes['NORMAL'])[indices]
        uvs = texture = None
        if 'material' in primitive and 'TEXCOORD_0' in attributes:
            material = doc['materials'][primitive['material']].get('name', '')
            texture = texture_for(material)
            if texture is not None:
                uvs = accessor(doc, binary, attributes['TEXCOORD_0'])[indices]
                textures.setdefault(texture, len(textures)+1)
        parts.append((positions, normals, uvs, texture))
    count = sum(len(part[0]) for part in parts)
    if not 3 <= count <= 360_000 or count % 3:
        raise ValueError('Weapon mesh exceeds the viewport triangle limit.')
    vertices = np.concatenate([part[0] for part in parts])
    if not np.isfinite(vertices).all() or not all(np.isfinite(part[1]).all() for part in parts):
        raise ValueError('Non-finite weapon geometry.')
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    extent = float(max(high-low))
    if extent <= 0:
        raise ValueError('Empty weapon geometry.')

    atlas = None
    if textures:
        columns = 1 << ((len(textures)).bit_length()+1 >> 1)
        rows = 1 << ((len(textures)//columns).bit_length())
        tile = min(512, 1024//max(columns, rows))
        atlas = Image.new('RGB', (columns*tile, rows*tile), 'white')
        for path, index in textures.items():
            with Image.open(BytesIO(path)) as image:
                atlas.paste(image.convert('RGB').resize((tile, tile), Image.Resampling.LANCZOS),
                            (index%columns*tile, index//columns*tile))
    model = [struct.pack('<4sIHH', b'T3M2', count, *atlas.size) if atlas
             else struct.pack('<4sI', b'T3M1', count)]
    center = (high+low)*0.5
    side_view = high[2]-low[2] > high[0]-low[0]
    for positions, normals, uvs, texture in parts:
        points = (positions-center)*(1.9/extent)
        if side_view:
            points = points[:, [2, 1, 0]] * (1, 1, -1)
            normals = normals[:, [2, 1, 0]] * (1, 1, -1)
        color = np.tile((1, 1, 1, 1) if texture else (.76, .79, .84, 1), (len(positions), 1))
        streams = (color, normals, points)
        if atlas:
            index = textures.get(texture, 0)
            coordinates = np.mod(uvs, 1.0) if uvs is not None else np.full((len(positions), 2), .5)
            coordinates = (coordinates*(tile-1)+(.5+index%columns*tile, .5+index//columns*tile))/atlas.size
            streams = (coordinates, *streams)
        model.append(np.asarray(np.column_stack(streams), dtype='<f4').tobytes())
    return b''.join((*model, atlas.tobytes())) if atlas else b''.join(model)


def metadata_key(raw):
    raw = raw.rsplit('.', 1)[0] if raw.startswith(CONTENT) else raw.split('.', 1)[0]
    return (asset_path(raw) if raw.startswith(CONTENT) else raw).casefold()


def metadata_for(validation, packages):
    roots = {row['family']: Path(row['path'].split('\\exports\\')[0])/'exports'/'metadata'
             for row in validation if '\\exports\\' in row['path']}
    materials, sockets = defaultdict(lambda: defaultdict(list)), []
    for family, members in packages.items():
        if family not in roots:
            continue
        for package in members:
            path = PurePosixPath(package)
            folder = roots[family] / path.with_suffix('').as_posix()
            if path.stem.startswith(('MIC_', 'MI_', 'MAT_', 'M_', 'MM_')):
                props = folder / f'{path.stem}.properties.json'
                if props.is_file():
                    values = {row['Name']: row['Tag'] for row in read_json(props)}
                    materials[family][path.stem].append({'asset': asset_path(package), **values})
            if path.stem.startswith(('SK_', 'SKL_', 'SKM_', 'MESH_')) and folder.is_dir():
                for record in folder.glob('SkeletalMeshSocket_*.properties.json'):
                    values = {row['Name']: row['Tag'] for row in read_json(record) if row['Name'] in SOCKET_FIELDS}
                    if 'SocketName' in values:
                        sockets.append(dict(package=asset_path(package), **values))
    return materials, sockets


def local_texture(material, materials, textures):
    matches = materials.get(material, [])
    if len(matches) != 1:
        return None
    for item in matches[0].get('TextureParameterValues', []):
        name = re.sub(r'[^a-z]', '', item.get('ParameterInfo', {}).get('Name', '').casefold())
        ref = item.get('ParameterValue')
        if name in COLOR_PARAMETERS and isinstance(ref, dict):
            row = textures.get(metadata_key(ref.get('ObjectPath', '')))
            if row is not None:
                return qualified_bytes(row)
    return None


def qualified_bytes(row):
    raw = Path(row['path']).read_bytes()
    if len(raw) != row['bytes'] or sha256(raw).hexdigest() != row['sha256']:
        raise ValueError(f"Verified export changed: {row['source_package']}")
    return raw


def build(scope, validated, extracted, output):
    sources = read_json(scope)['groups']
    validated_rows = read_json(validated)['files']
    packages = {family: sorted({row['path'] for row in group['members'] if row['path'].endswith('.uasset')})
                for family, group in sources.items()}
    materials, sockets = metadata_for(validated_rows, packages)
    catalog = {}
    inventory = {'format': 1, 'source': 'Retail TRIBES 3 cooked Windows weapon packages',
                 'assets': [], 'sockets': sockets, 'material_variants': materials, 'preview_issues': {}}
    exports = defaultdict(list)
    textures = {}
    for row in validated_rows:
        exports[row['source_package']].append(row)
        if row['kind'] == 'png':
            textures[asset_path(row['source_package']).casefold()] = row
    raw_files = defaultdict(list)
    for row in read_json(extracted)['files']:
        raw_files[PurePosixPath(row['package_member']).with_suffix('.uasset').as_posix()].append(row)

    (output/'models').mkdir()
    for family, files in packages.items():
        group = {}
        for package in files:
            rows = exports[package]
            mesh = PurePosixPath(package).stem
            view = asset_view(package)
            source = asset_path(package)
            inventory['assets'].append({'asset': source, 'family': family, 'view': view,
                                        'cooked_files': raw_files[package], 'exports': rows})
            geometry = next((row for row in rows if row['kind'] == 'glb'), None)
            if geometry is None and not MESH.match(mesh):
                continue
            filename = None
            if geometry:
                try:
                    preview = preview_model(qualified_bytes(geometry), lambda name: local_texture(
                        name, materials.get(family, {}), textures))
                    filename = sha256(source.encode()).hexdigest()[:16]+'.t3m'
                    (output/'models'/filename).write_bytes(preview)
                except (KeyError, IndexError, OSError, TypeError, ValueError, struct.error) as exc:
                    inventory['preview_issues'][source] = str(exc)
            label = model_label(mesh)
            entries = group.setdefault(view, {})
            if label in entries:
                label = f'{label} ({mesh})'
            if label in entries:
                label = package[len(CONTENT):].removesuffix('.uasset')
            entries[label] = filename
        if group:
            catalog[display_family(family)] = group

    for name, document in (('catalog.json', {'format': 1, 'weapons': catalog}), ('asset-inventory.json', inventory)):
        (output/name).write_text(json.dumps(document, indent=2)+'\n', encoding='utf-8')
    (output/'README.txt').write_text(
        'Private TRIBES 3 weapon library\n\n'
        'Armor > Weapons uses catalog.json and models/ on this PC.\n'
        'asset-inventory.json links to the locally verified cooked files and exports.\n'
        'The inventory records package variants, material parameters and recovered socket offsets.\n'
        'Package names alone do not establish which skins the retail menu offers.\n\n'
        'Original cooked packages target the retail Windows runtime. Their dependencies\n'
        'must be mounted by the matching game build. Availability as a standalone package\n'
        'has not been tested. GLB and T3M contain preview geometry. Import GLB into an\n'
        'Unreal editor project and cook new packages for another target or modified assets.\n'
        'Retail shader graphs, animation and gameplay need separate qualification.\n',
        encoding='utf-8')
    models = list((output/'models').glob('*.t3m'))
    print(f'{len(catalog)} weapon groups, {len(models)} previews, {len(sockets)} socket records', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('scope', 'validated', 'extracted', 'output'):
        parser.add_argument('--'+argument, type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or Path(__file__).resolve().parents[1] in output.parents:
        parser.error('Use a new private output folder outside the Git checkout.')
    with TemporaryDirectory(dir=output.parent) as temp:
        candidate = Path(temp)/'weapon-library'
        candidate.mkdir()
        build(args.scope, args.validated, args.extracted, candidate)
        candidate.rename(output)


if __name__ == '__main__':
    main()
