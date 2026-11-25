"""Check flag marker projection into the full-screen HUD canvas."""

from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = (Path(__file__).with_name('lua') / 'client.lua').read_text(encoding='utf-8')

FIXTURE = r"""
local f={viewport={X=1920,Y=1080},dpi=1.5,front=true}
local function valid(o) return type(o)=='table' end
local function same_object(a,b) return valid(a) and a==b end
local layout={}
function layout:GetViewportSize() return f.viewport end
function layout:GetViewportScale() return f.dpi end
local function StaticFindObject(path)
 if path=='/Script/UMG.Default__WidgetLayoutLibrary' then return layout end
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
  SetAnchors=function(self,value)
   assert(value.Minimum.X==value.Maximum.X and value.Minimum.Y==value.Maximum.Y)
   self.anchor=value.Minimum
  end,
  SetPosition=function(self,pos) assert(self.configured);self.position=pos end,
 }
end
local parent={}
f.entry={scale=0.25,widget={Slot=f.newSlot(),GetParent=function()return parent end,
 GetDesiredSize=function()return {X=80,Y=60}end}}
"""


class FlagMarkerProjectionTest(unittest.TestCase):
    def fixture(self):
        start = SOURCE.index('local function flag_marker_projection(valid)')
        end = SOURCE.index('-- Use the original overlay widgets', start)
        return LuaRuntime().execute(FIXTURE + SOURCE[start:end] + """
            local project=flag_marker_projection(valid)
            function f.project(x,y,z,lift)
                return project(f.entry,f.pc,{X=x,Y=y,Z=z or 0},lift)
            end
            return f
        """)

    def assert_on_screen(self, fixture, x, y):
        self.assertTrue(fixture.project(x, y))
        slot = fixture.entry.widget.Slot
        self.assertEqual((slot.position.X, slot.position.Y), (0, 0))
        self.assertAlmostEqual(slot.anchor.X * fixture.viewport.X, x)
        self.assertAlmostEqual(slot.anchor.Y * fixture.viewport.Y, y)

    def test_marker_follows_projected_target(self):
        fixture = self.fixture()
        for target in ((560, 83), (912, 341), (1194, 616)):
            self.assert_on_screen(fixture, *target)

    def test_resize_dpi_change_and_recreated_slot(self):
        fixture = self.fixture()
        self.assert_on_screen(fixture, 800, 500)
        fixture.viewport.X, fixture.viewport.Y = 960, 540
        fixture.dpi = 0.75
        fixture.entry.widget.Slot = fixture.newSlot()
        self.assert_on_screen(fixture, 400, 250)

    def test_offscreen_and_behind_camera_targets_stay_inside_viewport(self):
        fixture = self.fixture()
        for front, target in ((True, (5000, 540)), (False, (-40, 800))):
            fixture.front = front
            self.assertTrue(fixture.project(*target, 0, 40))
            anchor = fixture.entry.widget.Slot.anchor
            self.assertAlmostEqual(anchor.X * 1920, 1920 - (10+8)*1.5)
            self.assertAlmostEqual(anchor.Y * 1080, 540)

    def test_vertical_lift_keeps_horizontal_alignment_and_respects_the_top_edge(self):
        fixture = self.fixture()
        for lift, screen_y, expected_y in ((8, 500, 476.75), (40, 500, 428.75), (40, 70, 23.25)):
            with self.subTest(lift=lift, screen_y=screen_y):
                self.assertTrue(fixture.project(800, screen_y, 0, lift))
                anchor = fixture.entry.widget.Slot.anchor
                self.assertAlmostEqual(anchor.X * 1920, 800)
                self.assertAlmostEqual(anchor.Y * 1080, expected_y)

    def test_hud_pulse_updates_pickup_toss_and_return_without_a_native_widget_tick(self):
        start = SOURCE.index('local function enabled_flag_markers(env)')
        end = SOURCE.index('local shockLanceVisualFailed', start)
        helper = SOURCE[SOURCE.index('local function flag_hud_holder'):SOURCE.index('local ctfFlagHud=')]
        result = LuaRuntime().execute(r"""
            local function valid(o) return type(o)=='table' and not o.destroyed end
            local function same_object(a,b)
                return valid(a) and valid(b) and a:GetAddress()==b:GetAddress()
            end
            local world={GetAddress=function(self)return self end}
            local function actor(x)
                local a={x=x}
                function a:GetWorld() return world end
                function a:GetAddress() return self end
                function a:GetFullName() return tostring(self) end
                function a:SetRenderTransformPivot(v) self.pivot=v end
                function a:SetRenderScale(v) self.scale=v end
                function a:K2_GetActorLocation() return {X=self.x,Y=0,Z=0} end
                return a
            end
            local pc,ps,gs,pawn=actor(0),actor(0),actor(0),actor(0)
            ps.r_TeamId=1
            pc.PlayerState,pc.Pawn=ps,pawn
            function pc:IsLocalPlayerController() return true end
            function pc:HasAuthority() return false end
            pawn.bInitialized=true
            function pawn:GetHealth() return 1000 end
            function pawn:IsAlive() return true end
            local flags={actor(500),actor(1500)}
            for i,flag in ipairs(flags) do
                flag.r_TeamId,flag.mode=i,1
                flag.holderInfo={bReturned=false}
                flag.Mesh={owner=flag,centerZ=20}
                function flag:GetHeldBy() return self.holderInfo end
                function flag:GetOwner() return self.owner end
                function flag:GetFlagState() return self.mode end
            end
            local parent,widgets={visibility=1},{}
            function parent:GetWorld() return world end
            function parent:GetAddress() return self end
            function parent:GetVisibility() return self.visibility end
            function parent:SetVisibility(value) self.visibility=value end
            function parent:GetChildrenCount() return #widgets end
            function parent:GetChildAt(i) return widgets[i+1] end
            function parent:RemoveChildAt(i) table.remove(widgets,i+1) end
            function parent:AddChildToCanvas(widget) table.insert(widgets,widget) end
            local overlay={Flags=parent,GetWorld=parent.GetWorld,GetFullName=function()return '/Engine/Transient.test' end}
            local bases={actor(500),actor(1500),actor(2500)}
            bases[1].CachedFlag,bases[2].CachedFlag=flags[1],flags[2]
            for _,base in ipairs(bases) do
                base.returned={}
                function base:GetOwningPlayer() return pc end
                function base:OnFlagHeldChanged(flag,info,lastInfo)
                    assert(flag and info and lastInfo, 'native base callback requires three arguments')
                    self.returned[flag.r_TeamId]=info.bReturned
                    self.stateUpdates=(self.stateUpdates or 0)+1
                end
            end
            bases[3].GetOwningPlayer=function() return pawn end
            local library={}
            function library:Create()
                local w=actor(0)
                function w:GetParent() return parent end
                function w:UpdateFlagActor(flag) self.CachedActor=flag end
                function w:SetVisibility(value) self.visibility=value end
                function w:ShowOverlay(value) self.shown=value end
                function w:IsA() return true end
                function w:StopAllAnimations() self.stoppedAnimations=true end
                function w:OnFlagHeldChanged(flag,info,lastInfo)
                    assert(flag==self.CachedActor and info and lastInfo, 'native objective callback requires three arguments')
                    self.cachedReturned=info.bReturned
                    self.stateUpdates=(self.stateUpdates or 0)+1
                    if info.bReturned then
                        self.timerActive=false
                        self.timerShown=false
                        self.shown=false
                    end
                end
                w.BackgroundSwitcher={SetActiveWidget=function() end}
                w.ActionLabelGroup={SetVisibility=function() end}
                w.ActionText={SetText=function(self,v) self.text=v end}
                w.DistanceText={SetText=function() end}
                local container,content=actor(0),actor(0)
                container.Slot={SetAlignment=function(self,v) self.alignment=v end,
                    SetAnchors=function(self,v) self.anchors=v end}
                content.Slot={SetAlignment=function(self,v) self.alignment=v end}
                function content:GetParent() return container end
                function content:SetRenderTranslation(v) self.translation=v end
                function w:SetRenderTranslation(v) self.translation=v end
                w.Content=content
                return w
            end
            local system={}
            function system:GetComponentBounds(mesh,origin,extent)
                origin.X,origin.Y,origin.Z=mesh.owner.x,15,mesh.centerZ
                extent.Z=100
            end
            local function StaticFindObject(path)
                if path:find('KismetSystemLibrary',1,true) then return system end
                return path:find('Library',1,true) and library or {}
            end
            local function FindAllOf(name)
                if name=='TopPickup_Flag' then return flags end
                if name=='UI_Game_Overlay_FlagBase_C' then return bases end
                return {overlay}
            end
            local function FText(value) return value end
            local nextPulse
            local function ExecuteInGameThreadWithDelay(_,fn) nextPulse=fn end
            local function flag_marker_projection() return function(entry,_,target,lift)
                entry.widget.projectedX=target.X
                entry.widget.projectedY=target.Y
                entry.widget.projectedZ=target.Z
                entry.widget.lift=lift
                return true
            end end
        """ + helper + SOURCE[start:end] + r"""
            local noop=function()end
            local tick=enabled_flag_markers({valid=valid,signature=noop,report=noop,scope=noop})
            flags[2].holderInfo.bReturned=true
            tick(pc,ps,gs)
            nextPulse()
            local home,enemy=widgets[1],widgets[2]
            assert(not enemy.shown and enemy.cachedReturned)
            assert(enemy.TickFrequency==0 and enemy.stoppedAnimations)
            assert(enemy.scale.X==0.25 and enemy.scale.Y==0.25)
            assert(enemy.pivot.X==0.5 and enemy.pivot.Y==0.5)
            local duplicate=library:Create()
            duplicate:UpdateFlagActor(flags[2])
            parent:AddChildToCanvas(duplicate)
            local other=actor(0)
            function other:IsA() return false end
            parent:AddChildToCanvas(other)
            tick(pc,ps,gs)
            assert(#widgets==3 and widgets[2]==enemy and widgets[3]==other)
            assert(bases[2].scale.X==0.25)
            assert(enemy.Content:GetParent().Slot.anchors.Minimum.X==0.5)
            assert(enemy.Content.Slot.alignment.Y==0.5)
            assert(enemy.Content.translation.X==0 and enemy.Content.translation.Y==0)
            flags[2].holderInfo={bReturned=false}
            nextPulse()
            assert(parent.visibility==4 and enemy.shown and enemy.projectedX==1500)
            assert(enemy.projectedY==15 and enemy.projectedZ==120 and enemy.lift==8)
            local carrier=actor(1300)
            carrier.bInitialized,carrier.alive=true,true
            function carrier:IsAlive() return self.alive end
            carrier.Mesh={K2_GetComponentLocation=function()return {X=carrier.x,Y=-35,Z=100}end}
            carrier.CapsuleComponent={
                K2_GetComponentLocation=function()return {X=carrier.x,Y=5,Z=208}end,
                GetScaledCapsuleHalfHeight=function()return 100 end,
            }
            flags[2].holderInfo.Holder=carrier
            flags[2].owner=carrier
            flags[2].mode=2
            flags[2].x=900
            nextPulse()
            assert(enemy.shown and enemy.projectedX==1300 and enemy.projectedY==5)
            assert(enemy.projectedZ==332 and enemy.lift==8)
            carrier.x=1400
            flags[2].x=13000
            nextPulse()
            assert(enemy.projectedX==1400 and enemy.projectedZ==332 and enemy.lift==8)
            carrier.CapsuleComponent=nil
            nextPulse()
            assert(enemy.projectedX==1400 and enemy.projectedY==-35 and enemy.projectedZ==290)
            carrier.Mesh=nil
            nextPulse()
            assert(enemy.projectedX==1400 and enemy.projectedY==0 and enemy.projectedZ==190)
            carrier.alive=false -- The corpse and its owner pointer are still replicated.
            flags[2].x=1600
            nextPulse()
            assert(enemy.projectedX==1600 and enemy.projectedZ==120 and enemy.shown)
            carrier.alive=true
            flags[2].owner=nil -- A stale Holder must not keep the glyph on the thrower.
            flags[2].x=1000
            flags[2].mode=4
            nextPulse()
            assert(enemy.projectedX==1000 and enemy.projectedY==15 and enemy.projectedZ==120 and enemy.lift==8)
            local flagMesh=flags[2].Mesh
            flags[2].Mesh=nil
            nextPulse()
            assert(enemy.projectedX==1000 and enemy.projectedY==0 and enemy.projectedZ==150)
            flags[2].Mesh=flagMesh
            flags[2].r_HeldBy=flags[2].holderInfo
            flags[2].holderInfo.Holder=pawn
            flags[2].owner=pawn
            flags[2].mode=2
            nextPulse()
            assert(not enemy.shown and home.ActionText.text=='GO HERE')
            flags[2].owner=nil
            flags[2].x=900
            flags[2].mode=4
            nextPulse()
            assert(enemy.shown and enemy.projectedX==900 and home.ActionText.text=='DEFEND')
            enemy.projectedX=-1
            flags[2].Mesh.centerZ=75
            nextPulse()
            assert(enemy.projectedX==900 and enemy.projectedZ==175)
            assert(enemy.translation.X==0 and enemy.translation.Y==0)
            assert(enemy.Content.translation.X==0 and enemy.Content.translation.Y==0)
            enemy.timerActive,enemy.timerShown=true,true
            flags[2].holderInfo={Holder=pawn,bReturned=true}
            -- Return can arrive before movement and the old owner are cleared.
            flags[2].owner=pawn
            flags[2].mode=1
            nextPulse()
            assert(not enemy.shown and enemy.visibility==1)
            assert(enemy.cachedReturned and not enemy.timerActive and not enemy.timerShown)
            assert(home.ActionText.text=='DEFEND' and enemy.projectedX==900)
            assert(bases[1].returned[2] and bases[2].returned[2] and not bases[3].stateUpdates)
            local updates=enemy.stateUpdates
            local baseUpdates=bases[1].stateUpdates
            nextPulse()
            assert(not enemy.shown and enemy.stateUpdates==updates and bases[1].stateUpdates==baseUpdates)
            -- Picking up and dropping again must reactivate this same widget.
            flags[2].holderInfo={Holder=pawn,bReturned=false}
            flags[2].mode=2
            nextPulse()
            assert(not enemy.shown and not enemy.cachedReturned and home.ActionText.text=='GO HERE')
            assert(not bases[1].returned[2] and not bases[2].returned[2])
            flags[2].owner=nil
            flags[2].mode=4
            flags[2].x=1100
            nextPulse()
            assert(enemy.shown and enemy.projectedX==1100 and home.ActionText.text=='DEFEND')
            -- The same native reset must apply to a friendly returned flag.
            flags[1].mode=4
            flags[1].x=700
            nextPulse()
            assert(home.shown and home.ActionText.text=='RETURN' and home.projectedX==700)
            home.timerActive,home.timerShown=true,true
            flags[1].holderInfo={bReturned=true}
            flags[1].mode=1
            nextPulse()
            assert(not home.shown and home.visibility==1 and home.cachedReturned)
            assert(not home.timerActive and not home.timerShown and home.projectedX==700)
            assert(bases[1].returned[1] and bases[2].returned[1])
            bases[2].destroyed=true
            flags[2].holderInfo={Holder=pawn,bReturned=true}
            flags[2].owner=pawn
            flags[2].mode=1
            enemy.timerActive,enemy.timerShown=true,true
            nextPulse()
            assert(enemy.shown and enemy.visibility==4 and enemy.cachedReturned)
            assert(not enemy.timerActive and not enemy.timerShown and enemy.projectedX==1500)
            assert(enemy.projectedZ==120 and enemy.lift==8)
            return true
        """)
        self.assertTrue(result)
