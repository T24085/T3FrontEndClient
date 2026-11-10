"""Check the production flag marker against a translated and scaled HUD canvas."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = (Path(__file__).with_name('lua') / 'client.lua').read_text(encoding='utf-8')

FIXTURE = r"""
local f={geometry={X=160,Y=54,scale=1.25,width=1280,height=720},front=true}
local function valid(o) return type(o)=='table' end
local function same_object(a,b) return valid(a) and a==b end
local layout={}
function layout:GetViewportSize() return {X=1920,Y=1080} end
function layout:GetViewportScale() return 1.5 end
local slate={}
function slate:GetLocalSize(g) return {X=g.width,Y=g.height} end
function slate:ScreenToWidgetLocal(pc,g,p,out,includeWindowPosition)
 assert(pc==f.pc and not includeWindowPosition)
 out.LocalCoordinate={X=(p.X-g.X)/g.scale,Y=(p.Y-g.Y)/g.scale}
end
local function StaticFindObject(path)
 if path=='/Script/UMG.Default__WidgetLayoutLibrary' then return layout end
 if path=='/Script/UMG.Default__SlateBlueprintLibrary' then return slate end
end
f.pc={PlayerCameraManager={
 GetCameraLocation=function()return {X=0,Y=0,Z=0}end,
 GetCameraRotation=function()return {Yaw=0,Pitch=0}end,
}}
function f.pc:ProjectWorldLocationToScreen(target,out,relative)
 assert(relative==false)
 out.ScreenLocation={X=target.X,Y=target.Y}
 return f.front
end
function f.newSlot()
 return {
  SetAutoSize=function(self,value) assert(value);self.configured=true end,
  SetAlignment=function(_,value) assert(value.X==0.5 and value.Y==0.5) end,
  SetAnchors=function(_,value) assert(value.Minimum.X==0 and value.Maximum.Y==0) end,
  SetPosition=function(self,pos) assert(self.configured);self.position=pos end,
 }
end
local parent={GetCachedGeometry=function()return f.geometry end}
f.entry={widget={Slot=f.newSlot(),GetParent=function()return parent end,
 GetDesiredSize=function()return {X=80,Y=60}end}}
"""


class FlagMarkerProjectionTest(unittest.TestCase):
    def fixture(self):
        start = SOURCE.index('local function flag_marker_projection(valid)')
        end = SOURCE.index('-- Use the original overlay widgets', start)
        return LuaRuntime().execute(FIXTURE + SOURCE[start:end] + """
            local project=flag_marker_projection(valid)
            function f.project(x,y,z)
                return project(f.entry,f.pc,{X=x,Y=y,Z=z or 0})
            end
            return f
        """)

    def assert_on_screen(self, fixture, x, y):
        self.assertTrue(fixture.project(x, y))
        slot = fixture.entry.widget.Slot.position
        geometry = fixture.geometry
        self.assertAlmostEqual(geometry.X + slot.X * geometry.scale, x)
        self.assertAlmostEqual(geometry.Y + slot.Y * geometry.scale, y)

    def test_marker_follows_projected_target_inside_offset_canvas(self):
        fixture = self.fixture()
        for target in ((560, 83), (912, 341), (1194, 616)):
            self.assert_on_screen(fixture, *target)

    def test_canvas_layout_and_recreated_slot_are_read_on_next_frame(self):
        fixture = self.fixture()
        self.assert_on_screen(fixture, 800, 500)
        fixture.geometry.X = 240
        fixture.geometry.scale = 1.75
        fixture.entry.widget.Slot = fixture.newSlot()
        self.assert_on_screen(fixture, 800, 500)

    def test_offscreen_and_behind_camera_targets_stay_inside_viewport(self):
        fixture = self.fixture()
        geometry = fixture.geometry
        for front, target in ((True, (5000, 540)), (False, (-40, 800))):
            fixture.front = front
            self.assertTrue(fixture.project(*target))
            slot = fixture.entry.widget.Slot.position
            self.assertAlmostEqual(geometry.X + slot.X * geometry.scale, 1920 - (40+8)*1.5)
            self.assertAlmostEqual(geometry.Y + slot.Y * geometry.scale, 540)

    def test_unlaid_out_canvas_is_skipped(self):
        fixture = self.fixture()
        fixture.geometry.width = 0
        self.assertIsNone(fixture.project(800, 500))
        self.assertIsNone(fixture.entry.widget.Slot.position)
