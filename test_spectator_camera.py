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
local function object(name)
 serial=serial+1
 local obj={name=name,address=serial,alive=true}
 function obj:GetAddress()return self.address end
 function obj:GetFullName()return self.name end
 function obj:GetWorld()return world end
 function obj:HasAuthority()return false end
 function obj:IsA(class)return self.class==class.name end
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
function make_target(name)
 local t=object(name);t.class='/Script/Valhalla.ValCharacter';t.bInitialized=true
 t.PlayerState=object(name..'_state');t.PlayerState.PawnPrivate=t
 t.bForceOnlySpectatorToThirdPerson=true
 function t:AddComponentByClass(class)
  local component=object(class.name)
  function component:GetOwner()return t end
  function component:K2_AttachToComponent()return true end
  return component
 end
 -- An empty inventory models a retired replica. Native cleanup is outside
 -- this policy fixture; retained ownership is exercised by the runtime.
 function t:K2_GetComponentsByClass()return {}end
 return t
end
pc=object('observer');ps=object('observer_state');pc.PlayerState=ps
function ps:IsOnlyASpectator()return true end
local spectator=object('spectator_pawn')
pc.third=true;pc.AFKTimer=10;pc.directions={};pc.toggles=0
active=make_target('player_one')
function pc:IsLocalPlayerController()return true end
function pc:IsThirdPerson()return self.third end
function pc:ToggleThirdPerson()self.third=not self.third;self.toggles=self.toggles+1 end
function pc:GetViewTarget()return self.view end
function pc:GetSpectatorPawn()return spectator end
function pc:SetViewTargetWithBlend(target)self.view=target end
function pc:ServerViewSelf()self.view=spectator end
function pc:ServerRequestStartSpectating()self.view=active end
function pc:ServerSpectateNext(direction)
 self.directions[#self.directions+1]=direction;self.view=active
end
keys={};Key={F5='F5',F6='F6',F7='F7',F8='F8'}
function RegisterKeyBind(key,callback)keys[key]=callback end
function ExecuteInGameThread(callback)callback()end
local pending=nil;local handle=0
function ExecuteInGameThreadWithDelay(delay,callback)
 assert(not pending);pending=callback;handle=handle+1;return handle
end
function follow_once()local callback=assert(pending);pending=nil;callback()end
events={};applied={};polled={}
local materials={}
function materials.apply(target,third)
 assert(third==false and not pc.third,'first-person material policy required')
 applied[#applied+1]=target.name
end
function materials.poll(target,third)
 assert(third==false and not pc.third,'first-person material policy required')
 polled[#polled+1]=target.name
end
function materials.retire()end
function materials.owned()return {}end
env={lease_id='lease',watch_id='watch',now=function()return 100 end,
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

    def test_starts_first_person_and_only_offers_supported_controls(self):
        self.check('''
        assert(not pc.third and pc.toggles==1)
        assert(keys.F5 and keys.F6 and keys.F7 and not keys.F8)
        follow_once()
        assert(applied[1]=='player_one'and polled[1]=='player_one')
        assert(pc.AFKTimer==0)
        local ready=false
        for _,event in ipairs(events)do
         if event=='SPECTATOR_READY|lease=lease|watch=watch|mode=first'then ready=true end
         assert(not event:find('third_person',1,true))
        end
        assert(ready)
        ''')

    def test_native_or_legacy_third_person_requests_cannot_persist(self):
        self.check('''
        follow_once()
        pc.third=true;follow_once()
        assert(not pc.third and #applied==2)
        pc.third=true;service.action('third')
        assert(not pc.third and events[#events]=='SPECTATOR_VIEW|mode=first')
        pc.third=true;keys.F7()
        assert(not pc.third)
        ''')

    def test_next_previous_and_target_loss_stay_first_person(self):
        self.check('''
        follow_once()
        active=make_target('player_two');keys.F5();follow_once()
        assert(pc.directions[1]==1 and applied[#applied]=='player_two'and not pc.third)
        active=make_target('player_three');keys.F6();follow_once()
        assert(pc.directions[2]==-1 and applied[#applied]=='player_three'and not pc.third)
        active=nil;pc.view=nil;pc.third=true;follow_once()
        assert(not pc.third)
        active=make_target('respawned');keys.F5();follow_once()
        assert(polled[#polled]=='respawned'and not pc.third)
        ''')

    def test_runtime_fix_copy_matches_packaged_source(self):
        self.assertEqual((ROOT / 'lua/spectator_client.lua').read_bytes(),
                         (ROOT / 'runtime-fixes/spectator_client.lua').read_bytes())

    def test_ordinary_player_is_rejected_before_perspective_changes(self):
        self.check('''
        function ps:IsOnlyASpectator()return false end
        pc.third=true
        local ok=pcall(service.action,'first')
        assert(not ok and pc.third)
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
