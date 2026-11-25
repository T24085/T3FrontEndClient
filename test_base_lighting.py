from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = Path(__file__).resolve().with_name('lua') / 'client.lua'


class BaseLightingTest(unittest.TestCase):
    def test_draft_bakes_follow_independent_replicated_circuits(self):
        source = SOURCE.read_text(encoding='utf-8')
        block = source.split('local configure_draft_interior_lighting=', 1)[1].split('local allowedMaps=', 1)[0]
        lua = LuaRuntime()
        lua.execute('''
local ident=0
local function object(record)
 ident=ident+1
 local key=ident
 record.GetAddress=function() return key end
 return record
end
world=object({})
local package='/Game/Maps/Community/DraftT2001/Arena_DraftT2001_P.Arena_DraftT2001_P:'
local mesh='/Game/Community/T2Interiors/SM_Room.SM_Room'
local short='M_T2Baked_'..string.rep('a',32)
local material='/Game/Community/T2ModelTextures/'..short..'.'..short
local function generator(x)
 return object({r_TeamId=1,online=true,x=x,
  GetClass=function() return {GetFullName=function()
   return 'BlueprintGeneratedClass /Game/Topaz/Game/Objectives/BP_Objective_Generator.BP_Objective_Generator_C'
  end} end, GetWorld=function() return world end,
  K2_GetActorLocation=function(self) return {X=self.x,Y=10,Z=23} end,
  IsOnline=function(self) return self.online end})
end
gen1,gen2,gen3=generator(0),generator(200),generator(2400)
local function room(name)
 local base=object({GetFullName=function() return 'Material '..material end})
 local actor=object({GetWorld=function() return world end,
  GetFullName=function() return 'StaticMeshActor '..package..'PersistentLevel.'..name end})
 actor.StaticMeshComponent=object({
  assigned={[0]=base, [1]=base},StaticMesh={GetFullName=function() return 'StaticMesh '..mesh end},
  GetOwner=function() return actor end, GetMaterial=function(self,index) return self.assigned[index] end,
  SetMaterial=function(self,index,instance) self.assigned[index]=instance end})
 return actor.StaticMeshComponent,actor
end
local a,b
east,a=room('East')
west,b=room('West')
function FindAllOf() return {a,b} end
function valid(value) return value~=nil end
function FName(value) return value end
events={}
function report(value) events[#events+1]=value end
function loaded()
 return {CreateDynamicMaterialInstance=function()
  return object({SetScalarParameterValue=function(self,_,value) self.value=value end,
                 K2_GetScalarParameterValue=function(self) return self.value end})
 end}
end
local registry={GetArrayNum=function(self) return #self end}
registry[1]={Get=function() return gen3 end}
registry[2]={Get=function() if replicated then return gen1 end end}
registry[3]={Get=function() return gen2 end}
function duplicate_registrations()
 registry[4]=registry[1]
 registry[5]=registry[2]
 registry[6]=registry[3]
end
gs=object({r_Generators=registry,GetWorld=function() return world end,
 GetFullName=function() return 'GameState '..package..'PersistentLevel.GameState' end})
local function provider(group, x)
 return {role='generator',team=1,power_group=group,anchor_position_cm={x,0,0}}
end
local function binding(actor,group)
 return {actor=actor,asset=mesh,power_group=group,materials={{slot=0,asset=material}}}
end
mapDefinitions={DraftT2001={world=package,interior_power={
 entries={provider('T2Group11',0),provider('T2Group11',200),provider('T2Group12',2400)},
 groups={T2Group11={mode='generators',team=1},T2Group12={mode='generators',team=1}},
 interiors={binding('East','T2Group11'),binding('West','T2Group12')}
}}}
''')
        lua.globals().tick = lua.execute('return ' + block.strip())
        self.assertTrue(lua.execute('''
tick(gs)
assert(#events==0 and east.assigned[0].value==nil)
replicated=true; tick(gs)
assert(#events==2 and east.assigned[0].value==0 and west.assigned[0].value==0)
duplicate_registrations()
gen1.online=false; tick(gs)
assert(#events==2 and east.assigned[0].value==0)
gen2.online=false; tick(gs)
assert(#events==3 and east.assigned[0].value==1 and west.assigned[0].value==0)
assert(east.assigned[1].value==nil and west.assigned[1].value==nil)
gen2.x=2399; gen3.online=false; tick(gs)
assert(#events==3 and west.assigned[0].value==0)
gen2.x=200; gen2.online=true; tick(gs)
assert(#events==5 and east.assigned[0].value==0 and west.assigned[0].value==1)
return true
'''))

    def test_tagged_mesh_steady_light_and_blink_follow_team_power(self):
        source = SOURCE.read_text(encoding='utf-8')
        block = source.split('local configure_base_lighting=', 1)[1].split('local configure_water=', 1)[0]
        lua = LuaRuntime()
        lua.execute('''
world={GetAddress=function() return 1 end}
other={GetAddress=function() return 2 end}
mapDefinitions={}
function valid(obj) return obj~=nil end
function report() end
function FName(s) return s end
function actor(world,tags,light)
 local a={Tags=tags}
 tags.GetArrayNum=function() return #tags end
 function a:GetWorld() return world end
 function a:GetFullName() return 'Actor /Game/Test:PersistentLevel.Test' end
 function a:ActorHasTag(tag)
  for _,value in ipairs(tags) do if value==tag then return true end end
  return false
 end
 function a:SetActorHiddenInGame(hidden) self.hidden=hidden end
 if light then a.LightComponent={SetVisibility=function(self,on) self.visible=on end} end
 return a
end
normal=actor(world,{'CwPwr_T1_Normal'},false)
steady=actor(world,{'CwPwr_T1_Alarm'},true)
blink=actor(world,{'CwPwr_T1_Alarm','CwBlink'},false)
fast=actor(world,{'CwPwr_T1_Alarm','CwBlink_250'},true)
enemy=actor(world,{'CwPwr_T2_Alarm','CwBlink'},false)
mixed=actor(world,{'CwPwr_T1_Alarm','CwPwr_T1_Normal'},false)
foreign=actor(other,{'CwPwr_T1_Alarm','CwBlink'},false)
FindAllOf=function() return {normal,steady,blink,fast,enemy,mixed,foreign} end
local generator={r_TeamId=1,GetAddress=function() return 2 end,GetWorld=function() return world end,
                 IsOnline=function() return powered end}
gs={r_Generators={{Get=function() return generator end},GetArrayNum=function() return 1 end},
    GetAddress=function() return 3 end,GetWorld=function() return world end,
    GetFullName=function() return 'GameState /Game/Test:PersistentLevel.GameState' end,
    GetServerWorldTimeSeconds=function() return now end}
''')
        tick = lua.execute('return ' + block.strip())
        lua.globals().tick = tick
        self.assertTrue(lua.execute('''
powered=true; now=10; tick(gs)
assert(normal.hidden==false and steady.hidden and blink.hidden and fast.hidden and enemy.hidden)
powered=false; now=12; tick(gs)
assert(normal.hidden and not steady.hidden and steady.LightComponent.visible)
assert(not blink.hidden and not fast.hidden)
now=12.25; tick(gs)
assert(not blink.hidden and fast.hidden and not fast.LightComponent.visible)
now=12.5; tick(gs)
assert(blink.hidden and not fast.hidden)
assert(enemy.hidden and mixed.hidden==nil and foreign.hidden==nil)
powered=true; now=13; tick(gs)
assert(not normal.hidden and steady.hidden and blink.hidden and fast.hidden)
powered=false; now=15; tick(gs)
assert(not blink.hidden and not fast.hidden)
return true
'''))


if __name__ == '__main__':
    unittest.main()
