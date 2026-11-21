from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = Path(__file__).resolve().with_name('lua') / 'client.lua'


class BaseLightingTest(unittest.TestCase):
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
