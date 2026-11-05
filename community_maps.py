"""Canonical map identities; availability comes from each verified package."""
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class MapDefinition:
    id: str
    label: str
    asset_group: str
    level: str
    shared_group: str | None = None

    @property
    def package(self):
        return '/Game/Maps/Community/'+self.asset_group+'/'+self.level


DEFINITIONS=(
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


def map_ids(value):
    """Validate explicit identities without deriving package names from labels."""
    if (not isinstance(value,(list,tuple)) or not value
            or any(not isinstance(name,str) or name not in BY_ID for name in value)
            or len(set(value))!=len(value)):
        raise ValueError('Invalid explicit community map identities.')
    return tuple(value)


def declared_maps(manifest):
    return map_ids(manifest.get('community_maps',LEGACY_MAPS))


def declared_shared_content(manifest):
    """Parse explicit shared asset ownership once at the manifest boundary."""
    maps=declared_maps(manifest);groups=manifest.get('shared_content',{})
    if not isinstance(groups,dict):raise ValueError('Shared content ownership must be an object.')
    result={}
    for prefix,owners in groups.items():
        if not isinstance(prefix,str):raise ValueError('Shared content prefix must be a string.')
        path=PurePosixPath(prefix)
        if (len(path.parts)!=3 or path.parts[:2]!=('content','Community')
                or path.as_posix()+'/'!=prefix or ':'in prefix or'\\'in prefix
                or path.parts[-1]in('.','..')):
            raise ValueError('Shared content prefix must name one community asset group.')
        selected=map_ids(owners)
        if any(name not in maps for name in selected):raise ValueError('Shared content owner is not a declared map.')
        result[prefix]=selected
    return result


def options(ids):
    return [{'id':name,'label':BY_ID[name].label} for name in map_ids(ids)]
