"""Focused source simulator checks. Not native/RPC/rendering qualification."""
import hashlib,json,sys,unittest
from pathlib import Path
from lupa.lua54 import LuaRuntime
HERE=Path(__file__).resolve().parent;SOURCE=HERE/'tools/native_chaingun_peer.lua'
HARNESS=r'''
records={};registered={};unregistered={};fail_once=false;reject_schema=false
world={address=1};foreign_world={address=2}
function world:GetAddress()return self.address end
function foreign_world:GetAddress()return self.address end
function object(name,address,kind,selected)
 local o={name=name,address=address,kind=kind,selected=selected or world,bReplicates=false,bIsLocalProjectile=false}
 function o:GetAddress()return self.address end
 function o:GetWorld()return self.selected end
 function o:GetFullName()return self.name end
 function o:GetClass()return object(self.className or('Class '..self.name),self.address+100,'class',self.selected)end
 function o:HasAuthority()return false end
 function o:IsA(cls)
  if cls.name=='/Script/Valhalla.ValProjectile'then return self.kind=='projectile'end
  if cls.name=='/Script/Engine.Pawn'then return self.kind=='pawn'end
  return false
 end
 function o:GetOwner()return self.owner end
 function o:GetAudioVisual()return self.av end
 return o
end
mine=object('Pawn Local',10,'pawn');shooter=object('Pawn ActualShooter',20,'pawn');other=object('Pawn Other',25,'pawn')
projectile=object('Projectile Original',40,'projectile');projectile.Instigator=shooter
projectile.className='BlueprintGeneratedClass /Game/Topaz/Abilities/Weapons/LightChaingun/BP_Projectile_Topaz_LightChaingun.BP_Projectile_Topaz_LightChaingun_C'
projectile.NS_Projectile_Trail=object('Niagara OriginalTrail',45,'component')
projectile.av=object('Original AV',46,'asset');projectile.av.ProjectileTrail3P=object('NiagaraSystem Original3P',47,'asset')
asc=object('ASC OriginalShooter',50,'component');asc.owner=shooter
function param(value)return {get=function()return value end}end
function StaticFindObject(path)
 if path=='/Script/Valhalla.ValProjectile'or path=='/Script/Engine.Pawn'then return object(path,60,'class')end
 if path=='/Script/GameplayTags.GameplayTag'then
  local cls=object(path,70,'struct')
  function cls:ForEachProperty(cb)cb({GetFullName=function()return 'NameProperty /Script/GameplayTags.GameplayTag:TagName'end,GetOffset_Internal=function()return 0 end})end
  return cls
 end
 return object('Function '..path,80,'function')
end
function RegisterHook(path,pre,post)
 local n=#registered+1;registered[n]={path=path,pre=pre,post=post};return n,n+100
end
function UnregisterHook(path,pre,post)
 if fail_once then fail_once=false;error('simulated cleanup failure')end
 unregistered[#unregistered+1]={path=path,pre=pre,post=post}
end
function RegisterBeginPlayPostHook(callback)begin_callback=callback end
env={valid=function(o)return type(o)=='table'and o.address~=nil end,
 scope=function()end,signature=function(path,schema)if reject_schema then error('mismatched native schema')end end,
 report=function(row)records[#records+1]=row end,world=function()return world end,local_pawn=function()return mine end,
 accept_source=function(source)return source.address==shooter.address end}
'''
class Tests(unittest.TestCase):
 def setup_lua(self):
  lua=LuaRuntime();factory=lua.execute(SOURCE.read_text());lua.execute(HARNESS)
  service=factory(lua.globals().env);lua.globals().service=service
  return lua,service
 def test_exact_source_world_class_filter(self):
  lua,s=self.setup_lua();s.start()
  lua.execute("begin_callback(param(projectile));projectile.Instigator=mine;begin_callback(param(projectile));projectile.Instigator=other;begin_callback(param(projectile));projectile.Instigator=shooter;projectile.selected=foreign_world;begin_callback(param(projectile));projectile.selected=world;projectile.className='BlueprintGeneratedClass Other';begin_callback(param(projectile))")
  self.assertEqual(s.owned()['projectileIdentities'],1)
  self.assertEqual(s.owned()['totals']['accepted_source_events'],1)
  rows='\n'.join(lua.globals().records.values())
  self.assertIn('trail3P=NiagaraSystem Original3P',rows);self.assertIn('renderedAppearance=unverified',rows)
 def test_native_multicast_source_attribution(self):
  lua,s=self.setup_lua();s.start()
  lua.execute('registered[1].pre(param(asc),param({}));asc.owner=mine;registered[1].pre(param(asc),param({}))')
  self.assertEqual(s.owned()['totals']['accepted_source_cues'],1)
  self.assertEqual(s.owned()['totals']['unattributed_cue_calls'],1)
  self.assertIn('borrowed_native_GameplayTag_required','\n'.join(lua.globals().records.values()))
 def test_schema_mismatch_no_native_function_hook(self):
  lua,s=self.setup_lua();lua.execute('reject_schema=true');s.start()
  self.assertEqual(len(lua.globals().registered),0)
  self.assertEqual(s.owned()['processLifetimeRegistrationsRetained'],1)
  lua.execute('begin_callback(param(projectile))')
  self.assertEqual(s.owned()['projectileIdentities'],1)
 def test_cleanup_retains_failures_and_process_callback(self):
  lua,s=self.setup_lua();s.start();lua.execute('fail_once=true')
  state=s.stop();self.assertFalse(state['nativeFunctionHooksReleased']);self.assertTrue(state['callbackDisabled'])
  self.assertEqual(len(s.owned()['hooks']),1);self.assertEqual(s.owned()['hooks'][1]['pre'],1)
  state=s.stop();self.assertTrue(state['nativeFunctionHooksReleased']);self.assertTrue(state['requiresOriginalClientProcessCleanup'])
  self.assertEqual(state['processLifetimeRegistrationsRetained'],1)
  before=len(lua.globals().records);lua.execute('begin_callback(param(projectile))');self.assertEqual(before,len(lua.globals().records))
 def test_callback_output_bound_preserves_totals(self):
  lua,s=self.setup_lua();s.start();lua.execute('for i=1,500 do begin_callback(param(projectile))end')
  self.assertEqual(s.owned()['totals']['accepted_source_events'],500)
  s.stop();self.assertLessEqual(len(lua.globals().records),64)
  self.assertIn('accepted_source_events=500','\n'.join(lua.globals().records.values()))
if __name__=='__main__':unittest.main()
