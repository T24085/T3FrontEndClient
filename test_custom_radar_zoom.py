"""Check the native HUD zoom call on bundled and manifest-added community maps."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = (Path(__file__).with_name('lua') / 'client.lua').read_text(encoding='utf-8')

FIXTURE = r"""
local f={calls=0,helperTicks=0,events={},lookup=0}
local function valid(o) return type(o)=='table' end
local function same_object(a,b) return valid(a) and a==b end
local world,otherWorld={},{}
local pc={GetWorld=function()return world end,HasAuthority=function()return false end}
local gs={GetAddress=function()return 2 end,HasAuthority=function()return false end}
world.GetAddress=function()return 3 end
local function widget(address, owner)
 local w={CachedZoom=2,TargetZoom=2,DefaultZoom=1.5,CachedMapScale=0.001,Content={}}
 function w:GetOwningPlayer() return owner end
 function w:GetAddress() return address end
 function w:GetFullName() return 'Map'..address end
 function w:UpdateScale(delta)
  assert(delta==0 and self.CachedZoom==self.TargetZoom)
  self.Content.scale=2^(self.DefaultZoom*self.CachedZoom-1)
  f.calls=f.calls+1
 end
 w.Content.scale=2^(w.DefaultZoom*w.CachedZoom-1)
 return w
end
local miniClass='WidgetBlueprintGeneratedClass /Game/UI/Components/Game/UI_Game_MiniMap.UI_Game_MiniMap_C'
local function minimap(ownerWorld,map)
 return {Map=map,GetWorld=function()return ownerWorld end,GetClass=function()
  return {GetFullName=function()return miniClass end}
 end}
end
f.hud=widget(1,pc)
f.fullscreen=widget(2,pc)
f.foreign=widget(3,pc)
local function FindAllOf(name)
 assert(name=='UI_Game_MiniMap_C')
 f.lookup=f.lookup+1
 return {minimap(world,f.hud),minimap(otherWorld,f.foreign)}
end
local descriptors={
 Katabatic={name='Katabatic',world='retail:',package='/Game/Maps/Active/Katabatic/Level',native=true},
 KatabaticT2={name='KatabaticT2',world='manifest:',package='/Game/Maps/Community/KatabaticT2/Level',native=true},
 Scarabrae2026={name='Scarabrae2026',world='bundled:',package='/Game/Maps/Community/Scarabrae/Level',
     native_world_settings_class='/Script/Valhalla.ValWorldSettings'},
}
function gs:GetFullName() return f.current.world end
"""


class CustomRadarZoomTest(unittest.TestCase):
    def fixture(self):
        start = SOURCE.index('local function custom_radar_zoom(env)')
        end = SOURCE.index('local releaseRadarRuntime=releaseRadarRuntimeFactory', start)
        return LuaRuntime().execute(FIXTURE + SOURCE[start:end] + """
            local noop=function()return function()end end
            local runtime=releaseRadarRuntimeFactory({
                valid=valid, report=function(line)f.events[#f.events+1]=line end,scope=function()end,
                map_descriptors=descriptors,primary_assembly_factory=noop,guard_factory=noop,
                world_settings_guard_factory=noop,
                helper_factory=function()
                    return {tick=function()f.helperTicks=f.helperTicks+1;return true end,retire=function()end}
                end,
            })
            function f.tick(name)f.current=descriptors[name];runtime.tick(pc,gs)end
            return f
        """)

    def test_manifest_added_map_updates_only_its_hud_radar(self):
        f = self.fixture()
        original = f.hud.Content.scale
        f.tick('KatabaticT2')
        f.tick('KatabaticT2')
        self.assertAlmostEqual(f.hud.Content.scale / original, 2.25)
        self.assertEqual(f.calls, 1)
        self.assertEqual(f.helperTicks, 0)
        self.assertEqual(f.fullscreen.Content.scale, original)
        self.assertEqual(f.foreign.Content.scale, original)

    def test_bundled_map_reapplies_same_zoom_after_native_reset(self):
        f = self.fixture()
        f.tick('Scarabrae2026')
        target = f.hud.TargetZoom
        f.hud.CachedZoom = 2
        f.tick('Scarabrae2026')
        self.assertEqual(f.hud.CachedZoom, target)
        self.assertEqual(f.calls, 2)
        self.assertEqual(f.helperTicks, 2)

    def test_retail_map_skips_custom_radar_entirely(self):
        f = self.fixture()
        f.tick('Katabatic')
        self.assertEqual((f.lookup, f.calls, f.helperTicks), (0, 0, 0))
