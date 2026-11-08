"""Canonical map identities; availability comes from each verified package."""
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re


@dataclass(frozen=True)
class MapDefinition:
    id: str
    label: str
    asset_group: str
    level: str
    shared_group: str | None = None
    native: bool = False

    @property
    def package(self):
        return ('/Game/Maps/Active/' if self.native else '/Game/Maps/Community/')+self.asset_group+'/'+self.level


DEFINITIONS=(
    MapDefinition('Torment','Torment','Torment','Arena_Torment_P',native=True),
    MapDefinition('DangerousCrossing','Dangerous Crossing','DangerousCrossing','Arena_DangerousCrossing_P',native=True),
    MapDefinition('Drydock','Drydock','Drydock','Arena_Drydock_P',native=True),
    MapDefinition('Katabatic','Katabatic','Katabatic','Arena_Katabatic_P',native=True),
    MapDefinition('Wavemist','Wavemist','Wavemist','Arena_Wavemist_P',native=True),
    MapDefinition('Hollow','Hollow','Hollow','Arena_Hollow_P',native=True),
    MapDefinition('Raindance','Raindance','Raindance','Arena_Raindance_P',native=True),
    MapDefinition('Moonrise','Moonrise','Moonrise','Arena_Moonrise_P',native=True),
    MapDefinition('Stonehenge','Stonehenge','Stonehenge','Arena_Stonehenge_P'),
    MapDefinition('Snowblind','Snowblind (clear)','Snowblind','Arena_Snowblind_P'),
    MapDefinition('Rollercoaster','Rollercoaster','Rollercoaster','Arena_Rollercoaster_P'),
    MapDefinition('Damnation','Damnation','Damnation','Arena_Damnation_P','ClassicShared'),
    MapDefinition('HighOctane','High Octane','HighOctane','Arena_HighOctane_P','ClassicShared'),
    MapDefinition('Scarabrae','Scarabrae','Scarabrae','Arena_Scarabrae_P','ClassicShared'),
    MapDefinition('SnowblindBlizzard','Snowblind (weather)','Snowblind','Arena_Snowblind_Blizzard_P'),
    MapDefinition('HighOctane2026','High Octane (2026)','HighOctane','Arena_HighOctane_2026_P','ClassicShared'),
    MapDefinition('Damnation2026','Damnation (2026)','Damnation','Arena_Damnation_2026_P','ClassicShared'),
    MapDefinition('Scarabrae2026','Scarabrae (2026)','Scarabrae','Arena_Scarabrae_2026_P','ClassicShared'),
    MapDefinition('Stonehenge2026','Stonehenge (2026)','Stonehenge','Arena_Stonehenge_2026_P'),
    MapDefinition('Snowblind2026','Snowblind (clear) (2026)','Snowblind','Arena_Snowblind_2026_P'),
    MapDefinition('SnowblindBlizzard2026','Snowblind Blizzard (2026)','Snowblind','Arena_Snowblind_Blizzard_2026_P'),
    MapDefinition('Rollercoaster2026','Rollercoaster (2026)','Rollercoaster','Arena_Rollercoaster_2026_P'),
)
BY_ID={definition.id:definition for definition in DEFINITIONS}
LEGACY_MAPS=('Stonehenge','Snowblind','Rollercoaster')
MAP_ID = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}')
ASSET_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')
MAX_MAPS = 128


def valid_id(value):
    return isinstance(value, str) and MAP_ID.fullmatch(value) is not None


def valid_label(value):
    return isinstance(value, str) and 1 <= len(value) <= 64 and value == value.strip() and value.isprintable()


def custom_definitions(value):
    if not isinstance(value, dict) or len(value) > MAX_MAPS - len(BY_ID):
        raise ValueError('Invalid custom map definitions.')
    ids = {name.casefold() for name in BY_ID}
    labels = {item.label.casefold() for item in BY_ID.values()}
    packages = {item.package.casefold() for item in BY_ID.values()}
    result = {}
    for name, row in value.items():
        if (not valid_id(name) or name.casefold() in ids or not isinstance(row, dict)
                or set(row) != {'label', 'asset_group', 'level'} or not valid_label(row['label'])
                or row['label'].casefold() in labels
                or any(not isinstance(row[key], str) or not ASSET_NAME.fullmatch(row[key])
                       for key in ('asset_group', 'level'))):
            raise ValueError('Invalid or duplicate custom map identity.')
        definition = MapDefinition(name, row['label'], row['asset_group'], row['level'])
        if definition.package.casefold() in packages:
            raise ValueError('Duplicate custom level package.')
        ids.add(name.casefold())
        labels.add(definition.label.casefold())
        packages.add(definition.package.casefold())
        result[name] = definition
    return result


def map_ids(value, definitions=BY_ID):
    """Validate explicit identities without deriving package names from labels."""
    if (not isinstance(value,(list,tuple)) or not value
            or any(not isinstance(name,str) or name not in definitions for name in value)
            or len(set(value))!=len(value)):
        raise ValueError('Invalid explicit community map identities.')
    return tuple(value)


def declared_definitions(manifest):
    extra = custom_definitions(manifest.get('map_definitions', {}))
    definitions = {**BY_ID, **extra}
    maps = map_ids(manifest.get('community_maps', LEGACY_MAPS), definitions)
    if not extra.keys() <= set(maps):
        raise ValueError('Custom map definition is outside the published catalog.')
    return {name: definitions[name] for name in maps}


def declared_maps(manifest):
    return tuple(declared_definitions(manifest))


def declared_shared_content(manifest, definitions=None):
    """Parse explicit shared asset ownership once at the manifest boundary."""
    maps=declared_definitions(manifest) if definitions is None else definitions
    groups=manifest.get('shared_content',{})
    if not isinstance(groups,dict):raise ValueError('Shared content ownership must be an object.')
    result={}
    for prefix,owners in groups.items():
        if not isinstance(prefix,str):raise ValueError('Shared content prefix must be a string.')
        path=PurePosixPath(prefix)
        if (len(path.parts)!=3 or path.parts[:2]!=('content','Community')
                or path.as_posix()+'/'!=prefix or ':'in prefix or'\\'in prefix
                or path.parts[-1]in('.','..')):
            raise ValueError('Shared content prefix must name one community asset group.')
        selected=map_ids(owners,maps)
        result[prefix]=selected
    return result


def options(ids, definitions=BY_ID):
    return [{'id':name,'label':definitions[name].label} for name in map_ids(ids, definitions)]


def read_options(items, *, dynamic=False):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_MAPS:
        raise ValueError('Invalid lobby map list.')
    names, labels = set(), set()
    for row in items:
        if (not isinstance(row, dict) or set(row) != {'id', 'label'} or not valid_id(row['id'])
                or not valid_label(row['label']) or row['id'].casefold() in names or row['label'].casefold() in labels
                or (row['id'] in BY_ID and row['label'] != BY_ID[row['id']].label)
                or (not dynamic and row['id'] not in BY_ID)):
            raise ValueError('Invalid lobby map option.')
        names.add(row['id'].casefold())
        labels.add(row['label'].casefold())
    return {row['id']: row['label'] for row in items}


def lua_map_definitions(root, run, selected):
    """Extend the bundled Lua definitions with one verified data-only descriptor."""
    bundled = root / 'lua/community_maps.lua'
    if selected is None or selected.id in BY_ID:
        return bundled
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    key = quote(selected.id)
    world = selected.package + '.' + selected.level + ':'
    generated = run / 'catalog-map.lua'
    with generated.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(f'local maps=assert(loadfile({quote(bundled.as_posix())}))()\n'
                     f'assert(maps[{key}]==nil,"duplicate_catalog_map")\n'
                     f'maps[{key}]={{name={key},package={quote(selected.package)},world={quote(world)},'
                     'native=true,native_world_settings_class="/Script/Valhalla.ValWorldSettings"}\n'
                     'return maps\n')
    return generated
