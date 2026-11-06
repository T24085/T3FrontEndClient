"""Candidate trail scope tests; rendered native confirmation remains separate."""
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
f.projectile=o('Projectile');f.projectile.Instigator=f.pawn
function f.projectile:GetClass()return o('BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/HeavyBoltLauncher/BP_Projectile_Topaz_HeavyBoltLauncher.BP_Projectile_Topaz_HeavyBoltLauncher_C')end
function f.projectile:GetAudioVisual()return{IsValid=function()return true end,ProjectileTrail1P=f.one,ProjectileTrail3P=f.three}end
f.trail=o('Trail');f.trail.Asset=f.one
function f.trail:GetOwner()return f.projectile end
function f.trail:SetAsset(asset,reset)assert(asset==f.three and reset==false);self.Asset=asset;f.changes=f.changes+1 end
f.projectile.NS_Projectile_Trail=f.trail
function FindAllOf(name)assert(name=='BP_Projectile_Topaz_HeavyBoltLauncher_C');return{f.projectile}end
f.env={valid=function(a)return a~=nil and a:IsValid()end,scope=function()end,signature=function()end,report=function(s)f.events[#f.events+1]=s end}
return f
"""
class HeavyBoltTests(unittest.TestCase):
 def fixture(self):
  lua=LuaRuntime(unpack_returned_tuples=True,max_memory=8*1024*1024);f=lua.execute(FIXTURE)
  f.service=lua.execute((ROOT/'runtime-fixes/heavy_bolt_visual.lua').read_text())(f.env)
  return f
 def test_stowing_uses_original_world_trail_once(self):
  f=self.fixture();f.service(f.pc,f.pawn,f.asc,20);f.service(f.pc,f.pawn,f.asc,20)
  self.assertEqual(f.changes,1)
 def test_client_predicted_projectile_with_local_authority_also_changes(self):
  f=self.fixture();f.projectile.authority=True;f.service(f.pc,f.pawn,f.asc,20)
  self.assertEqual(f.changes,1)
 def test_equipped_bolt_and_unrelated_weapon_never_change(self):
  f=self.fixture();f.service(f.pc,f.pawn,f.asc,16);self.assertEqual(f.changes,0)
  f.otherGun=True;f.service(f.pc,f.pawn,f.asc,20);self.assertEqual(f.changes,0)
 def test_remote_authority_other_instigator_and_unknown_trail_excluded(self):
  for field in ('remote','authority','instigator','asset'):
   f=self.fixture()
   if field=='remote':f.remote=True
   elif field=='authority':f.pc.authority=True
   elif field=='instigator':f.projectile.Instigator=None
   else:f.trail.Asset=f.three
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
