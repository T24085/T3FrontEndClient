"""Heavy Bolt trail selection scope and weapon input isolation."""
from pathlib import Path
import unittest
from lupa.lua54 import LuaRuntime
ROOT=Path(__file__).resolve().parent
FIXTURE=r"""
local f={changes=0,equipped=false,events={}}
local id=0
local function o(name)
 id=id+1;local a={id=id,name=name,alive=true,authority=false}
 function a:IsValid()return self.alive end
 function a:GetAddress()return self.id end
 function a:GetFullName()return self.name end
 function a:HasAuthority()return self.authority end
 function a:GetWorld()return f.world end
 return a
end
f.world=o('World');f.pc=o('PC');f.pawn=o('Pawn');f.asc=o('ASC')
f.pc.Pawn=f.pawn;f.pawn.Controller=f.pc;f.pawn.AbilitySystemComponent=f.asc
function f.pc:IsLocalPlayerController()return not f.remote end
function f.asc:GetOwner()return f.pawn end
local gun='BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/GA_Topaz_HeavyBoltLauncher.GA_Topaz_HeavyBoltLauncher_C'
f.ability=o('Ability');function f.ability:GetClass()return o(f.otherGun and'OtherGun'or gun)end
f.asc.ActivatableAbilities={Items={}}
function f.asc.ActivatableAbilities.Items:ForEach(cb)cb(1,{get=function()return{InputID=5,Handle={Handle=16},Ability=f.ability}end})end
local base='/Game/VFX/Weapons/BoltLauncher/Heavy/Projectile/NS_BoltLauncher_Heavy_Projectile_'
f.one=o('NiagaraSystem '..base..'1P.NS_BoltLauncher_Heavy_Projectile_1P')
f.three=o('NiagaraSystem '..base..'3P.NS_BoltLauncher_Heavy_Projectile_3P')
local visualPath='/Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/AV_Topaz_HeavyBoltLauncher.AV_Topaz_HeavyBoltLauncher'
local reloadPath='NiagaraSystem /Game/VFX/Weapons/BoltLauncher/Heavy/Reload/'
local function effect(name,socket)
 return {ParticleSystem=o(reloadPath..name..'.'..name),SocketName={ToString=function()return socket end}}
end
function f.newVisual()
 local visual=o('ValDeviceAudioVisual '..visualPath)
 visual.ProjectileTrail3P=f.three
 f.orb=effect('NS_BoltLauncher_Heavy_Bolt_Reload','EnergyBullet_Socket')
 f.tether=effect('NS_BoltLauncher_Heavy_EnergyTether_Reload','MuzzleSocket')
 f.other=effect('Other','MuzzleSocket')
 visual.ReloadActions={ForEach=function(_,callback)
  for i,action in ipairs({f.orb,f.tether,f.other})do callback(i,{get=function()return action end})end
 end}
 local first=f.one
 return setmetatable(visual,{
  __index=function(_,key)if key=='ProjectileTrail1P'then return first end end,
  __newindex=function(self,key,value)
   if key=='ProjectileTrail1P'then first=value;f.changes=f.changes+1 else rawset(self,key,value)end
  end})
end
f.visual=f.newVisual()
function StaticFindObject(path)assert(path==visualPath);if not f.unloaded then return f.visual end end
f.env={valid=function(a)return a~=nil and a:IsValid()end,scope=function()end,signature=function()end,report=function(s)f.events[#f.events+1]=s end}
return f
"""
class HeavyBoltTests(unittest.TestCase):
 def test_client_embeds_the_canonical_visual_guard(self):
  client=(ROOT/'lua/client.lua').read_text()
  prefix='local heavyBoltVisualFactory=(function()\n'
  embedded=client.split(prefix,1)[1].split('\nend)()',1)[0]
  self.assertEqual(embedded,(ROOT/'runtime-fixes/heavy_bolt_visual.lua').read_text().strip())
 def fixture(self):
  lua=LuaRuntime(unpack_returned_tuples=True,max_memory=8*1024*1024);f=lua.execute(FIXTURE)
  f.service=lua.execute((ROOT/'runtime-fixes/heavy_bolt_visual.lua').read_text())(f.env)
  return f
 def test_equipped_bolt_uses_world_trail_before_a_projectile_exists(self):
  f=self.fixture();f.service(f.pc,f.pawn,f.asc,16);f.service(f.pc,f.pawn,f.asc,20)
  self.assertEqual(f.visual.ProjectileTrail1P.GetAddress(f.visual.ProjectileTrail1P),f.three.GetAddress(f.three))
  self.assertIsNone(f.orb.ParticleSystem)
  self.assertIsNone(f.tether.ParticleSystem)
  self.assertIsNotNone(f.other.ParticleSystem)
  self.assertEqual(f.changes,1)
 def test_unknown_reload_action_leaves_visual_data_intact(self):
  f=self.fixture();f.orb.SocketName=f.tether.SocketName;f.service(f.pc,f.pawn,f.asc,16)
  self.assertIsNotNone(f.orb.ParticleSystem)
  self.assertIsNotNone(f.tether.ParticleSystem)
  self.assertEqual(f.changes,0)
 def test_late_loaded_and_reloaded_visual_data_is_handled(self):
  f=self.fixture();f.unloaded=True;f.service(f.pc,f.pawn,f.asc,16);self.assertEqual(f.changes,0)
  f.unloaded=False;f.service(f.pc,f.pawn,f.asc,16);self.assertEqual(f.changes,1)
  f.visual.alive=False;f.visual=f.newVisual();f.service(f.pc,f.pawn,f.asc,16);self.assertEqual(f.changes,2)
 def test_remote_authority_foreign_ability_and_unknown_trail_excluded(self):
  for field in ('remote','authority','otherGun','asset','visual'):
   f=self.fixture()
   if field=='remote':f.remote=True
   elif field=='authority':f.pc.authority=True
   elif field=='otherGun':f.otherGun=True
   elif field=='asset':f.one.name='Unrelated Niagara System'
   else:f.visual.name='Unrelated AudioVisual Data'
   f.service(f.pc,f.pawn,f.asc,20);self.assertEqual(f.changes,0)
class VisualIsolationTests(unittest.TestCase):
 def test_visual_failure_preserves_native_input_release_and_schedule(self):
  lua=LuaRuntime(unpack_returned_tuples=True,max_memory=8*1024*1024)
  f=lua.execute((ROOT/'tools/weapon_visual_isolation_fixture.lua').read_text())
  observer=lua.execute((ROOT/'runtime-fixes/weapon_input.lua').read_text())(f.env)
  observer(f.pc,f.ps);f.tick();f.pressed=False;f.tick()
  self.assertEqual(f.releases,1);self.assertEqual(len(f.queue),1)
  events=[f.events[i]for i in range(1,len(f.events)+1)]
  self.assertEqual(sum('HEAVY_BOLT_VISUAL_ERROR|'in e for e in events),1)
  self.assertFalse(any('WEAPON_INPUT_ERROR|'in e for e in events))
if __name__=='__main__':unittest.main()
