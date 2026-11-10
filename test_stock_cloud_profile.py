"""Exercise the cloud profile against loaded and missing world actors."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime

from client_entry import STOCK_CLOUD_MAPS, stock_cloud_arguments
from community_maps import BY_ID


SOURCE = (Path(__file__).with_name('lua') / 'client.lua').read_text(encoding='utf-8')
PROFILE = SOURCE[SOURCE.index('local configure_stock_clouds='):SOURCE.index('local function client_tick(')]
FIXTURE = r"""
local f={scans=0, writes=0, spawned=0, reports={}}
local mapDefinitions={}
for _,name in ipairs({'Stonehenge2026','SnowblindBlizzard2026','KatabaticMyrkwood','KatabaticT2'}) do
    mapDefinitions[name]={name=name,world='/Game/'..name..':'}
end
local world,other={},{}
local function valid(value) return type(value)=='table' end
local function same_object(a,b) return valid(a) and a==b end
local function report(line) table.insert(f.reports,line) end
local function FindAllOf(kind) assert(kind=='VolumetricCloud');f.scans=f.scans+1;return f.actors end
local asset='/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst.m_SimpleVolumetricCloud_Inst'
local function StaticFindObject() return nil end
local function LoadAsset(path)
    assert(path==asset)
    if not f.missing then return {GetFullName=function() return 'MaterialInstanceConstant '..path end} end
end
local class={}
local function loaded(path,identity)
    assert(path=='/Script/Engine.VolumetricCloud' and identity=='Class '..path)
    return class
end
local function cloud(owner)
    return {
        GetWorld=function() return owner end,
        VolumetricCloudComponent={
            LayerBottomAltitude=2,LayerHeight=6,ViewSampleCountScale=0.58,
            SetMaterial=function(self,value) f.writes=f.writes+1;self.Material=value end,
            SetLayerBottomAltitude=function(self,value) self.LayerBottomAltitude=value end,
            SetLayerHeight=function(self,value) self.LayerHeight=value end,
            SetViewSampleCountScale=function(self,value) self.ViewSampleCountScale=value end,
        },
    }
end
function world:SpawnActor(kind,position,rotation)
    assert(kind==class and position.Z==0 and rotation.Roll==0)
    f.spawned=f.spawned+1;f.owned=cloud(self);return f.owned
end
f.own=cloud(world)
f.foreign=cloud(other)
f.actors={f.foreign,f.own}
function f.state(name)
    return {GetFullName=function() return '/Game/'..name..':GameState' end,GetWorld=function() return world end}
end
"""


def runtime(map_id):
    lua = LuaRuntime()
    code = PROFILE.replace('@@STOCK_CLOUD_MAP@@', f'"{map_id}"')
    return lua, lua.execute(FIXTURE + code + '\nreturn f,configure_stock_clouds')


class StockCloudProfileTest(unittest.TestCase):
    def test_temporal_reconstruction_targets_only_affected_community_maps(self):
        prefix = '-ini:Engine:[SystemSettings]:r.VolumetricRenderTarget'
        for map_id in STOCK_CLOUD_MAPS - {'Stonehenge2026'}:
            with self.subTest(map_id=map_id):
                self.assertEqual(stock_cloud_arguments(map_id), [prefix + '=1', prefix + '.Mode=2'])
        self.assertEqual(stock_cloud_arguments('Stonehenge2026'), [prefix + '=0'])
        self.assertEqual(stock_cloud_arguments('KatabaticT2'), [])
        self.assertEqual(stock_cloud_arguments('Drydock'), [])

    def test_scope_excludes_katabatic_t2_and_retail(self):
        self.assertEqual(STOCK_CLOUD_MAPS, {'KatabaticMyrkwood'} | {key for key in BY_ID if key.endswith('2026')})
        _, (fixture, tick) = runtime('')
        tick(fixture.state('KatabaticT2'))
        self.assertEqual(fixture.scans, 0)

    def test_stonehenge_uses_reference_layer_in_its_own_world_once(self):
        _, (fixture, tick) = runtime('Stonehenge2026')
        tick(fixture.state('KatabaticT2'))
        self.assertEqual(fixture.scans, 0)
        tick(fixture.state('Stonehenge2026'))
        tick(fixture.state('Stonehenge2026'))
        component = fixture.own.VolumetricCloudComponent
        self.assertEqual((component.LayerBottomAltitude, component.LayerHeight), (3.5, 4.0))
        self.assertEqual(component.ViewSampleCountScale, 0.58)
        self.assertEqual((fixture.writes, fixture.spawned), (1, 0))
        self.assertIsNone(fixture.foreign.VolumetricCloudComponent.Material)

    def test_snowblind_keeps_layer_and_waits_for_the_authored_actor(self):
        lua, (fixture, tick) = runtime('SnowblindBlizzard2026')
        fixture.actors = lua.table_from([fixture.foreign])
        tick(fixture.state('SnowblindBlizzard2026'))
        fixture.actors[2] = fixture.own
        tick(fixture.state('SnowblindBlizzard2026'))
        component = fixture.own.VolumetricCloudComponent
        self.assertEqual((component.LayerBottomAltitude, component.LayerHeight), (2, 6))
        self.assertEqual(component.ViewSampleCountScale, 1.0)
        self.assertEqual((fixture.writes, fixture.spawned), (1, 0))

    def test_myrkwood_creates_one_layer_only_with_a_valid_material(self):
        for missing in (False, True):
            lua, (fixture, tick) = runtime('KatabaticMyrkwood')
            fixture.actors = lua.table_from([fixture.foreign])
            fixture.missing = missing
            tick(fixture.state('KatabaticMyrkwood'))
            tick(fixture.state('KatabaticMyrkwood'))
            self.assertEqual((fixture.writes, fixture.spawned), (0, 0) if missing else (1, 1))
            self.assertEqual(len(fixture.reports), 1)
            self.assertIn('UNAVAILABLE' if missing else 'APPLIED', fixture.reports[1])
