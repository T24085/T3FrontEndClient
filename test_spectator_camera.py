"""Run the real Lua camera policy against a small observer-only engine fixture."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from lupa.lua54 import LuaRuntime

from build_dynamic_client import SPECTATOR_RUNTIME_FILES, build_candidate, copy_spectator_runtime, verified_source


ROOT = Path(__file__).resolve().parent
FIXTURE = r'''
local serial=0
world=nil
function object(name)
 serial=serial+1
 local obj={name=name,address=serial,alive=true,active=true}
 function obj:GetAddress()return self.address end
 function obj:GetFullName()return self.name end
 function obj:GetWorld()return world end
 function obj:HasAuthority()return false end
 function obj:IsA(class)return self.class==class.name end
 function obj:IsActive()return self.active end
 function obj:SetActive(active)self.active=active end
 return obj
end
world=object('world')
local function property(name,kind,offset,owner)
 local p={}
 function p:GetFName()return {ToString=function()return name end}end
 function p:GetFullName()return kind..' /Script/Valhalla.'..owner..':'..name end
 function p:GetOffset_Internal()return offset end
 return p
end
local classes={}
function StaticFindObject(name)
 if not classes[name]then
  local c=object(name);classes[name]=c
  function c:ForEachProperty(callback)
   if name=='/Script/Valhalla.ValCharacter'then
    for _,field in ipairs({{'FirstPersonCameraComponent','ObjectProperty',2024},
      {'ThirdPersonCameraBoom','ObjectProperty',2032},{'ThirdPersonCameraComponent','ObjectProperty',2040},
      {'bForceOnlySpectatorToThirdPerson','BoolProperty',6896}})do
     callback(property(field[1],field[2],field[3],'ValCharacter'))
    end
   elseif name=='/Script/Valhalla.ValPlayerController'then
    callback(property('AFKTimer','FloatProperty',3924,'ValPlayerController'))
   end
  end
 end
 return classes[name]
end
function FName(name)return name end
local kismetMaterials=StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary')
function kismetMaterials:CreateDynamicMaterialInstance(component,parent)
 local material=object(parent.name..'_mid')
 function material:SetScalarParameterValue(key,value)self[key]=value end
 return material
end
local sys=StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
probes={};obstacles={}
function sys:SphereTraceSingleForObjects(target,start,finish,radius,types,complex,ignore,_,hit)
 assert(types[1]==0 and #types==1 and complex and ignore[1]==target and radius==16)
 assert(finish.Z>start.Z)
 probes[#probes+1]={start=start,finish=finish}
 local time=table.remove(obstacles,1)
 if time then hit.Time=time;return true end
 return false
end
local skiRow=object('ski_row')
skiRow.class='/Script/UMG.PanelWidget'
local widgets={}
function FindAllOf(class)
 assert(class=='TextBlock')
 return widgets
end
function make_label(name,value,row)
 local widget=object(name);widget.class='/Script/UMG.TextBlock'
 widget.text=value;widget.visibility=4
 function widget:GetText()return {ToString=function()return self.text end}end
 function widget:GetParent()return row end
 function widget:GetVisibility()return self.visibility end
 function widget:SetVisibility(mode)self.visibility=mode end
 widgets[#widgets+1]=widget
 return widget
end
skiValue=make_label('ski_value','Text Block',skiRow)
local skiTitle=make_label('ski_title','SKI TOGGLE',skiRow)
unrelated=make_label('unrelated','Text Block',nil)
function skiRow:GetChildrenCount()return 2 end
function skiRow:GetChildAt(index)return index==0 and skiTitle or skiValue end
function make_target(name)
 local t=object(name);t.class='/Script/Valhalla.ValCharacter';t.bInitialized=true
 t.PlayerState=object(name..'_state');t.PlayerState.PawnPrivate=t
 t.bForceOnlySpectatorToThirdPerson=true
 t.aim={Pitch=0,Yaw=0,Roll=0}
 function t:GetBaseAimRotation()return self.aim end
 t.RootComponent=object(name..'_root')
 function t.RootComponent:GetOwner()return t end
 t.RootComponent.position={X=0,Y=0,Z=100}
 function t.RootComponent:K2_GetComponentLocation()return self.position end
 function t:GetMesh3P()return self.visual end
 t.nativeArms=object(name..'_native_arms');t.nativeGun=object(name..'_native_gun')
 function t:GetMesh1P()return self.nativeArms end
 function t:GetGunMesh1P()return self.nativeGun end
 function t:GetActiveEquipSlotAV()return self.av end
 function t:GetGunMesh3P()return self.worldGun end
 function t:GetJetpackMesh()return nil end
 t.alpha=0
 t.eye=object(name..'_eye');t.FirstPersonCameraComponent=t.eye
 t.eye.FieldOfView=104;t.eye.position={X=0,Y=0,Z=64}
 function t.eye:GetOwner()return t end
 function t.eye:K2_GetComponentLocation()return self.position end
 function t:GetThirdPersonCameraAlpha()return self.alpha end
 function t:AddComponentByClass(class,manual,transform)
  local component=object(class.name)
  component.height=transform.Translation.Z
  function component:GetOwner()return t end
  function component:K2_AttachToComponent(parent,socket,locationRule)
   assert(socket=='None' and ((parent==t.RootComponent and (locationRule==0 or locationRule==1))
    or (parent==t.eye and locationRule==2) or (parent==t.visual and locationRule==1) or (parent==t.FirstPersonCameraComponent and locationRule==2)))
   self.parent=parent
   return true
  end
  component.visible=true
  function component:SetVisibility(visible)self.visible=visible end
  function component:IsVisible()return self.visible end
  function component:SetCollisionEnabled(value)assert(value==0)end
  function component:SetCastShadow(value)assert(not value)end
  function component:SetBoundsScale(value)self.boundsScale=value end
  function component:SetSkeletalMeshAsset(asset)self.mesh=asset end
  function component:GetSkeletalMeshAsset()return self.mesh end
  function component:SetAnimClass(animation)self.animation=animation end
  function component:GetNumMaterials()return self.mesh and 1 or 0 end
  function component:GetMaterial()return self.material or self.mesh end
  function component:SetMaterial(slot,material)assert(slot==0);self.material=material end
  function component:SetLeaderPoseComponent(leader,refresh,tick)assert(refresh and not tick);self.poseLeader=leader end
  function component:K2_GetComponentLocation()return self.parent:K2_GetComponentLocation()end
  function component:K2_SetWorldRotation(rotation)self.rotation=rotation end
  function component:SetAbsolute(location,rotation,scale)assert(not location and rotation and not scale)end
  function component:K2_SetWorldLocationAndRotation(location,rotation)self.location=location;self.rotation=rotation end
  return component
 end
 -- An empty inventory models a retired replica. Native cleanup is outside
 -- this policy fixture; retained ownership is exercised by the runtime.
 function t:K2_GetComponentsByClass()return {}end
 return t
end
pc=object('observer');ps=object('observer_state');pc.PlayerState=ps
function ps:IsOnlyASpectator()return true end
local spectator=object('spectator_pawn');pc.spectator=spectator
pc.third=false;pc.AFKTimer=10;pc.directions={};pc.toggles=0;pc.camera_refreshes=0
pc.PlayerCameraManager=object('camera_manager')
pc.PlayerCameraManager.location={X=0,Y=0,Z=64}
function pc.PlayerCameraManager:GetCameraLocation()return self.location end
active=make_target('player_one')
function pc:IsLocalPlayerController()return true end
function pc:IsThirdPerson()return self.third end
function pc:ToggleThirdPerson()self.third=not self.third;self.toggles=self.toggles+1 end
function pc:GetViewTarget()return self.view end
function pc:GetSpectatorPawn()return self.spectator end
function pc:SetViewTargetWithBlend(target)self.view=target;self.camera_refreshes=self.camera_refreshes+1 end
function pc:ServerViewSelf()self.view=spectator end
function pc:ServerRequestStartSpectating()self.view=active end
function pc:ServerSpectateNext(direction)
 self.directions[#self.directions+1]=direction;self.view=active
end
keys={};Key={LEFT_MOUSE_BUTTON='left',RIGHT_MOUSE_BUTTON='right',MIDDLE_MOUSE_BUTTON='middle',F7='F7',F8='F8'}
function RegisterKeyBind(key,callback)keys[key]=callback end
function ExecuteInGameThread(callback)callback()end
local pending=nil;local handle=0
function ExecuteInGameThreadWithDelay(delay,callback)
 assert(not pending);pending=callback;handle=handle+1;return handle
end
function follow_once()local callback=assert(pending);pending=nil;callback()end
events={};applied={};polled={};presentations={}
local materials={}
function materials.apply(target,third)
 presentations[#presentations+1]=third
 applied[#applied+1]=target.name
end
function materials.poll(target,third)
 assert(third==presentations[#presentations],'poll must keep the current presentation')
 polled[#polled+1]=target.name
end
retirements=0
function materials.retire()retirements=retirements+1 end
function materials.owned()return {}end
clock=100
env={lease_id='lease',watch_id='watch',now=function()return clock end,
 valid=function(obj)return type(obj)=='table'and obj.alive==true end,
 scope=function()end,signature=function()end,
 report=function(event)events[#events+1]=event end,
 material_factory=function()return materials end}
gameState=object('game_state')
'''


class SpectatorCameraTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(FIXTURE)
        factory = self.lua.execute((ROOT / 'lua/spectator_client.lua').read_text(encoding='utf-8'))
        self.lua.globals().service = factory(self.lua.globals().env)
        self.lua.execute('service.tick(pc,ps,gameState)')

    def check(self, code):
        self.lua.execute(code)
        self.lua.execute("for _,event in ipairs(events)do assert(not event:find('RUNTIME_ERROR',1,true),event)end")

    def test_starts_in_chase_view_and_uses_mouse_controls(self):
        self.check('''
        assert(pc.third and pc.toggles==1)
        assert(keys.left and keys.right and keys.middle)
        assert(keys.F7 and keys.F8 and not (keys.F5 or keys.F6))
        active.alpha=1;pc.PlayerCameraManager.location.X=-300
        follow_once()
        follow_once()
        assert(applied[1]=='player_one'and polled[1]=='player_one'and presentations[1]==true)
        assert(pc.AFKTimer==0)
        local ready=false
        for _,event in ipairs(events)do
         if event=='SPECTATOR_READY|lease=lease|watch=watch|mode=third'then ready=true end
        end
        assert(ready)
        ''')

    def test_camera_input_selects_the_matching_body_presentation(self):
        self.check('''
        keys.middle();follow_once()
        keys.middle()
        assert(pc.third and events[#events]=='SPECTATOR_VIEW|mode=third')
        follow_once()
        assert(#presentations==2 and presentations[1]==false and presentations[2]==true)
        active.alpha=1
        pc.PlayerCameraManager.location.X=-300
        follow_once()
        assert(#presentations==2 and presentations[2]==true)
        pc.PlayerCameraManager.location.X=0
        keys.middle();active.alpha=0;follow_once()
        assert(not pc.third and #presentations==3)
        follow_once()
        assert(#presentations==3 and presentations[3]==false)
        ''')

    def test_close_chase_camera_keeps_full_body_presentation(self):
        self.check('''
        follow_once();active.alpha=1
        pc.PlayerCameraManager.location.X=-42;follow_once()
        assert(pc.third and #presentations==1 and presentations[1]==true)
        pc.PlayerCameraManager.location.X=-100;follow_once()
        pc.PlayerCameraManager.location.X=-72;follow_once()
        assert(#presentations==1 and presentations[1]==true)
        pc.PlayerCameraManager.location.X=-50;follow_once()
        assert(#presentations==1 and presentations[1]==true)
        assert(active.ThirdPersonCameraBoom.TargetArmLength==580 and active.ThirdPersonCameraComponent.location.Z>280)
        ''')

    def test_chase_uses_aim_yaw_and_stays_above_the_player_at_extreme_pitch(self):
        self.check('''
        active.aim={Pitch=85,Yaw=90,Roll=31};follow_once()
        local arm,camera=active.ThirdPersonCameraBoom,active.ThirdPersonCameraComponent
        assert(arm.TargetArmLength==580 and camera.rotation.Yaw==90 and camera.rotation.Pitch==-14 and camera.rotation.Roll==0)
        assert(not arm.bUsePawnControlRotation and not arm.bDoCollisionTest)
        local shot=probes[#probes]
        assert(shot.start.Z==148 and shot.finish.Z>280 and shot.finish.Y<-550)
        active.aim.Pitch=-85;follow_once()
        assert(camera.rotation.Pitch==-14 and arm.TargetArmLength==580)
        ''')

    def test_chase_tries_an_elevated_view_and_a_shoulder_view_before_closing_in(self):
        self.check('''
        obstacles={.08};follow_once()
        local arm,camera=active.ThirdPersonCameraBoom,active.ThirdPersonCameraComponent
        assert(#probes==2 and camera.rotation.Pitch==-34 and arm.TargetArmLength==580)
        obstacles={.08,.1};follow_once()
        assert(#probes==5 and camera.rotation.Pitch==-26 and camera.rotation.Yaw==55 and arm.TargetArmLength==580)
        obstacles={.08,.2,.15,.3};follow_once()
        assert(#probes==9 and camera.rotation.Yaw==-55 and arm.TargetArmLength==166)
        follow_once()
        assert(camera.rotation.Pitch==-14 and arm.TargetArmLength==211)
        ''')

    def test_chase_follows_the_rendered_mesh_and_eases_wrapped_aim(self):
        self.check('''
        active.visual=make_target('mesh_holder').RootComponent
        local mesh=active.visual
        function mesh:GetOwner()return active end
        mesh.position={X=0,Y=0,Z=15}
        active.aim.Yaw=175
        follow_once()
        local rig=service.owned().rig
        assert(rig.camera.parent==mesh and rig.camera.rotation.Yaw==175)
        assert(probes[#probes].start.Z==148)

        active.RootComponent.position.X=250
        mesh.position.X=75
        active.aim.Yaw=-175
        follow_once()
        assert(rig.camera.rotation.Yaw==177.5 and probes[#probes].start.X==75)
        follow_once()
        assert(rig.camera.rotation.Yaw==179.375)
        ''')

    def test_first_person_keeps_full_body_until_eye_is_the_rendered_view(self):
        self.check('''
        follow_once()
        local rig=service.owned().rig
        assert(rig.camera:IsActive() and not active.eye:IsActive())
        pc.PlayerCameraManager.location.X=-450
        keys.F7();follow_once()
        assert(not pc.third and rig.first:IsActive() and not rig.camera:IsActive())
        assert(presentations[#presentations]==true)
        pc.PlayerCameraManager.location.X=0
        follow_once()
        assert(presentations[#presentations]==false)
        keys.F8()
        assert(rig.camera:IsActive() and not rig.first:IsActive())
        assert(presentations[#presentations]==true)
        ''')

    def test_remote_viewmodel_follows_weapon_changes_and_restores_world_gun(self):
        self.check('''
        local function reference(path)
         return {GetObjectID=function()return {GetAssetPathName=function()
          return {ToString=function()return path end}end}end}
        end
        local avOne=object('av-one');avOne.Mesh1P=reference('/Game/One.One')
        avOne.ABP1P=reference('/Game/OneAnim.OneAnim_C')
        local avTwo=object('av-two');avTwo.Mesh1P=reference('/Game/Two.Two')
        avTwo.ABP1P=reference('/Game/TwoAnim.TwoAnim_C')
        active.nativeArms=nil;active.nativeGun=nil
        active.worldGun=object('remote-world-gun')
        active.worldGun.visible=true
        function active.worldGun:GetOwner()return active end
        function active.worldGun:IsVisible()return self.visible end
        function active.worldGun:SetVisibility(value)self.visible=value end
        active.av=avOne
        follow_once();keys.F7();follow_once()
        local rig=service.owned().rig
        assert(rig.viewArms:IsVisible() and rig.viewGun:IsVisible() and not active.worldGun.visible)
        assert(rig.viewGun.mesh.name=='/Game/One.One' and rig.viewGun.animation.name=='/Game/OneAnim.OneAnim_C')
        local gun=rig.viewGun
        assert(rig.viewArms.poseLeader==gun and gun.material['RenderToForeground?']==1)
        assert(rig.viewArms.boundsScale==2 and gun.boundsScale==6)
        active.av=avTwo;follow_once()
        assert(gun==rig.viewGun and gun.mesh.name=='/Game/Two.Two' and gun:IsVisible())
        assert(gun.material.name=='/Game/Two.Two_mid' and gun.material['RenderToForeground?']==1)
        keys.F8();follow_once()
        assert(not gun:IsVisible() and not rig.viewArms:IsVisible() and active.worldGun.visible)
        ''')

    def test_missing_remote_equipment_keeps_full_native_body(self):
        self.check('''
        active.nativeArms=nil;active.nativeGun=nil
        follow_once();keys.F7();follow_once()
        assert(not pc.third and presentations[#presentations]==true)
        assert(service.owned().rig.viewGun==nil)
        ''')

    def test_first_person_skips_chase_collision_queries(self):
        self.check('''
        follow_once();local before=#probes
        keys.F7();follow_once()
        assert(#probes==before and not pc.third)
        keys.F8();assert(#probes>before and pc.third)
        ''')

    def test_perspective_keys_rebind_a_cached_camera_even_with_cursor_visible(self):
        self.check('''
        follow_once();pc.bShowMouseCursor=true
        keys.F7();assert(not pc.third and presentations[#presentations]==false)
        local before=pc.camera_refreshes
        keys.F7();assert(not pc.third and pc.camera_refreshes==before+2)
        keys.F8();assert(pc.third and presentations[#presentations]==true)
        ''')

    def test_late_native_third_person_policy_is_repaired_and_retained_for_cleanup(self):
        self.check('''
        follow_once();keys.F7()
        local before=pc.camera_refreshes
        active.bForceOnlySpectatorToThirdPerson=true
        follow_once()
        assert(not active.bForceOnlySpectatorToThirdPerson and not pc.third)
        assert(pc.camera_refreshes==before+2)
        assert(service.owned().rig.originalForce and service.owned().rig.changedForce)
        ''')

    def test_hud_hides_only_ski_placeholder_and_restores_valid_text(self):
        self.check('''
        follow_once()
        assert(skiValue.visibility==1 and unrelated.visibility==4)
        skiValue.text='DISENGAGED';follow_once()
        assert(skiValue.visibility==4)
        ''')

    def test_native_death_camera_repairs_only_remote_views_and_stops_at_respawn(self):
        factory = self.lua.execute((ROOT / 'lua/spectator_client.lua').read_text(encoding='utf-8'))
        self.lua.globals().factory = factory
        self.lua.execute(FIXTURE)
        self.check('''
        function ps:IsOnlyASpectator()return false end
        env.passive=true
        service=factory(env)
        pc.view=active
        pc.Pawn=active
        service.observe_native(pc,ps,gameState)
        assert(#presentations==0)
        ps.r_bDead=true
        service.observe_native(pc,ps,gameState)
        assert(#presentations==0)
        pc.Pawn=nil
        pc.PlayerCameraManager.location.X=-300
        service.observe_native(pc,ps,gameState)
        assert(presentations[1]==true and pc.view==active and pc.toggles==0)
        assert(pc.AFKTimer==10 and not next(keys)and #pc.directions==0)
        local before=retirements
        ps.r_bDead=false
        follow_once()
        assert(retirements==before+1 and skiValue.visibility==4)
        assert(pc.view==active and pc.toggles==0)
        for _,event in ipairs(events)do assert(not event:find('SPECTATOR_READY',1,true))end
        ''')

    def test_retiring_restores_the_previous_ski_visibility(self):
        self.check('''
        follow_once()
        assert(skiValue.visibility==1)
        service.retire()
        assert(skiValue.visibility==4)
        ''')

    def test_next_previous_and_respawn_preserve_selected_perspective(self):
        self.check('''
        follow_once()
        active=make_target('player_two');keys.left();follow_once()
        assert(pc.directions[1]==1 and applied[#applied]=='player_two'and pc.third)
        active=make_target('player_three');keys.right();follow_once()
        assert(pc.directions[2]==-1 and applied[#applied]=='player_three'and pc.third)
        active=nil;pc.view=nil;pc.third=false;follow_once()
        assert(pc.third)
        active=make_target('respawned');keys.left();follow_once()
        assert(applied[#applied]=='respawned'and pc.third)
        ''')

    def test_clicks_leave_menus_alone(self):
        self.check('''
        pc.bShowMouseCursor=true
        keys.left();keys.right();keys.middle()
        assert(#pc.directions==0 and pc.third)
        pc.bShowMouseCursor=false
        keys.left();keys.right();keys.middle()
        assert(pc.directions[1]==1 and pc.directions[2]==-1 and not pc.third)
        ''')

    def test_runtime_fix_copy_matches_packaged_source(self):
        self.assertEqual((ROOT / 'lua/spectator_client.lua').read_bytes(),
                         (ROOT / 'runtime-fixes/spectator_client.lua').read_bytes())

    def test_ordinary_player_is_ignored_before_perspective_changes(self):
        self.check('''
        function ps:IsOnlyASpectator()return false end
        pc.Pawn=active
        keys.F7();follow_once()
        assert(pc.third and pc.AFKTimer==10 and #presentations==0)
        ''')

    def test_first_person_tracks_the_native_eye_and_current_aim(self):
        self.check('''
        follow_once();active.aim={Pitch=32,Yaw=-125,Roll=7};keys.F7()
        local lens=active.FirstPersonCameraComponent
        assert(lens~=active.eye and lens.parent==active.eye)
        assert(lens.FieldOfView==104 and lens:K2_GetComponentLocation().Z==64)
        assert(lens.rotation.Pitch==32 and lens.rotation.Yaw==-125 and lens.rotation.Roll==7)
        active.eye.position={X=52,Y=30,Z=116}
        assert(lens:K2_GetComponentLocation().X==52 and lens:K2_GetComponentLocation().Z==116)
        active.aim={Pitch=-18,Yaw=85,Roll=0};follow_once()
        assert(lens.rotation.Pitch==-18 and lens.rotation.Yaw==85)
        keys.F8();keys.F7();assert(active.FirstPersonCameraComponent==lens)
        ''')

    def test_missing_spectator_pawn_and_local_state_are_retried(self):
        self.check('''
        follow_once()
        local pawn=pc.spectator;pc.spectator=nil
        local refreshes=pc.camera_refreshes
        keys.F7();follow_once()
        local lens=active.FirstPersonCameraComponent
        assert(not pc.third and pc.camera_refreshes==refreshes and presentations[#presentations]==true)
        pc.PlayerState=nil;pc.AFKTimer=7;follow_once()
        assert(pc.AFKTimer==7 and lens==active.FirstPersonCameraComponent)
        pc.spectator=pawn;pc.PlayerState=ps;follow_once()
        assert(pc.camera_refreshes==refreshes+2 and presentations[#presentations]==false)
        assert(lens==active.FirstPersonCameraComponent and pc.AFKTimer==0)
        ''')

    def test_delayed_engine_perspective_change_keeps_requested_mode(self):
        self.check('''
        follow_once()
        function pc:ToggleThirdPerson()self.toggles=self.toggles+1 end
        keys.F7();follow_once();follow_once()
        assert(pc.third and pc.toggles==2)
        clock=clock+1;follow_once()
        assert(pc.toggles==3)
        pc.third=false;follow_once()
        assert(presentations[#presentations]==false and active.FirstPersonCameraComponent.parent==active.eye)
        ''')

    def test_builder_replaces_stale_verified_camera_and_keeps_feature_gating(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / 'lua').mkdir()
            for name in SPECTATOR_RUNTIME_FILES:
                (output / name).write_text('old verified source', encoding='utf-8')
            copy_spectator_runtime({}, output)
            self.assertEqual((output / SPECTATOR_RUNTIME_FILES[0]).read_text(), 'old verified source')
            copy_spectator_runtime({'spectator_contract': 'native-spectator-v1'}, output)
            for name in SPECTATOR_RUNTIME_FILES:
                self.assertEqual((output / name).read_bytes(), (ROOT / name).read_bytes())

    def test_dynamic_candidate_inventories_current_camera_without_changing_input(self):
        with tempfile.TemporaryDirectory() as folder:
            # Windows hosted runners may expose TEMP through a short-name alias.
            base = Path(folder).resolve()
            source, output = base / 'source', base / 'candidate'
            required = ('client.py', 'connection-policy.json', 'lib/client_support.py',
                        'lib/owned_native_session.py', 'client_preparation.py', 'startup_timing.py',
                        'startup_paths.py', 'lua/client.lua', *SPECTATOR_RUNTIME_FILES)
            files = []
            for name in required:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'old verified fixture')
                files.append(dict(path=name, bytes=path.stat().st_size,
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            manifest = dict(build_id='fixture', startup_contract='prepared-client-v1',
                            spectator_contract='native-spectator-v1', community_maps=['Stonehenge'], files=files)
            (source / 'package-manifest.json').write_text(json.dumps(manifest))
            build_candidate(source, output)
            result, _ = verified_source(output)
            self.assertEqual(result['spectator_contract'], 'native-spectator-v1')
            for name in SPECTATOR_RUNTIME_FILES:
                self.assertEqual((output / name).read_bytes(), (ROOT / name).read_bytes())
                self.assertEqual((source / name).read_bytes(), b'old verified fixture')


if __name__ == '__main__':
    unittest.main()
