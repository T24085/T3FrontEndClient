"""Exercise the client lighting changes against the current cooked actor layouts."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = (Path(__file__).with_name('lua') / 'client.lua').read_text(encoding='utf-8')
PROFILE = SOURCE[SOURCE.index('local configure_community_lighting='):SOURCE.index('local configure_stock_clouds=')]
FIXTURE = r"""
local f={reads=0,writes=0,reports={},actors={}}
local world={}
local function valid(value) return type(value)=='table' end
local function same_object(a,b) return valid(a) and a==b end
local function report(line) table.insert(f.reports,line) end
local function signature(path,fields)
    assert(path:match('^/Script/Engine%.[^:]+:Set'))
    assert(fields[1][2]=='FloatProperty' and fields[1][3]==0)
    if f.badSignature and path:find(f.badSignature,1,true) then error('signature mismatch') end
end
local function StaticFindObject(path)
    f.reads=f.reads+1
    return f.actors[path]
end
local function setter(field)
    return function(self,value) f.writes=f.writes+1;self[field]=value end
end
function f.load(group,level,intensity)
    local prefix='/Game/Maps/Community/'..group..'/'..level..'.'..level..':PersistentLevel.'
    f.sky={Intensity=intensity,SetIntensity=setter('Intensity')}
    f.fog={FogDensity=0.45,StartDistance=1575,FogMaxOpacity=1,
        SetFogDensity=setter('FogDensity'),SetStartDistance=setter('StartDistance'),
        SetFogMaxOpacity=setter('FogMaxOpacity')}
    local function actor(kind,field,component)
        local path=prefix..kind..'_0'
        local object={GetWorld=function() return world end,
            GetFullName=function() return kind..' '..path end,[field]=component}
        f.actors[path]=object
        return object
    end
    f.skyActor=actor('SkyLight','LightComponent',f.sky)
    f.fogActor=actor('ExponentialHeightFog','Component',f.fog)
    return {GetFullName=function() return 'ValGameState '..prefix..'GameState' end,
        GetWorld=function() return world end}
end
"""


class CommunityLightingTest(unittest.TestCase):
    def setUp(self):
        self.start_candidate()

    def start_candidate(self):
        self.lua = LuaRuntime()
        self.fx, self.tick = self.lua.execute(FIXTURE + PROFILE + 'return f,configure_community_lighting')

    def load_quagmire(self):
        return self.fx.load('QuagmireTWLT2', 'Arena_QuagmireTWLT2_2026_P', 6)

    def test_quagmire_reduces_fill_and_fog_once(self):
        state = self.load_quagmire()
        self.tick(state)
        self.tick(state)
        self.assertEqual(self.fx.sky.Intensity, 3)
        self.assertEqual((self.fx.fog.FogDensity, self.fx.fog.StartDistance, self.fx.fog.FogMaxOpacity),
                         (0.14, 3000, 0.82))
        self.assertEqual((self.fx.reads, self.fx.writes), (2, 4))
        self.assertIn('APPLIED|map=QuagmireTWLT22026', self.fx.reports[1])

    def test_extra_ambient_fill_is_reduced_without_touching_other_maps_fog(self):
        for group, baseline, target in [('MinotaurT2', 6, 3), ('BeggarsRunTWLT2', 9, 4)]:
            with self.subTest(map=group):
                self.start_candidate()
                self.tick(self.fx.load(group, f'Arena_{group}_2026_P', baseline))
                self.assertEqual(self.fx.sky.Intensity, target)
                self.assertEqual((self.fx.reads, self.fx.writes), (1, 1))

    def test_unlisted_level_does_not_look_up_actors(self):
        self.tick(self.fx.load('KatabaticT2', 'Arena_KatabaticT2_2026_P', 6))
        self.assertEqual(self.fx.reads, 0)

    def test_waits_for_the_current_world_fog_component(self):
        state = self.load_quagmire()
        own_world = self.fx.fogActor.GetWorld
        self.fx.fogActor.GetWorld = self.lua.eval('function() return {} end')
        self.tick(state)
        self.assertEqual(self.fx.writes, 0)
        self.fx.fogActor.GetWorld = own_world
        self.tick(state)
        self.assertEqual(self.fx.writes, 4)

    def test_new_authored_values_are_kept(self):
        state = self.load_quagmire()
        self.fx.fog.StartDistance = 30000
        self.tick(state)
        self.assertEqual(self.fx.writes, 0)
        self.assertIn('authored_values_changed', self.fx.reports[1])

    def test_native_signature_mismatch_prevents_all_writes(self):
        state = self.load_quagmire()
        self.fx.badSignature = 'SetFogMaxOpacity'
        self.tick(state)
        self.assertEqual(self.fx.writes, 0)
        self.assertIn('UNAVAILABLE', self.fx.reports[1])
