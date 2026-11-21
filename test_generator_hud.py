"""Regression fixtures for the native score bar generator binding."""
from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


SOURCE = Path(__file__).resolve().with_name('lua') / 'client.lua'


class GeneratorHudTest(unittest.TestCase):
    def test_late_generator_rebuilds_and_keeps_other_icons(self):
        source = SOURCE.read_text(encoding='utf-8')
        start = source.index('local function same_object', source.index('local scoreBarClass'))
        end = source.index('local function refresh_ctf_score_bar', start)
        lua = LuaRuntime()
        lua.execute('''
function valid(o) return o~=nil end
function report() end
local function object(id) return {GetAddress=function()return id end} end
world=object(1)
local function generator(id,team)
 local actor=object(id)
 actor.r_TeamId=team
 actor.GetWorld=function()return world end
 return actor
end
g1,g2,g3,g4=generator(10,1),generator(11,1),generator(12,2),generator(13,2)
function icon(actor)
 return {CachedActor=actor,GetClass=function()
  return {GetFullName=function()
   return 'WidgetBlueprintGeneratedClass /Game/UI/Components/Game/WBP_Game_GeneratorIcon.WBP_Game_GeneratorIcon_C'
  end}
 end}
end
function panel(items)
 return {items=items,GetChildrenCount=function(self)return #self.items end,
         GetChildAt=function(self,i)return self.items[i+1] end,
         RemoveChildAt=function(self,i)table.remove(self.items,i+1) end}
end
function StaticFindObject(path) return {GetFullName=function()return 'Function '..path end} end
local function weak(get) return {Get=get} end
now,late,binds=0,nil,0
gs={r_Generators={weak(function()return g1 end),weak(function()return late end),
                  weak(function()return g3 end),weak(function()return g4 end),
                  GetArrayNum=function()return 4 end},
    GetServerWorldTimeSeconds=function()return now end}
widget={FriendlyGenerators=panel({icon(g1),icon(g1)}),EnemyGenerators=panel({icon(g3),icon(g4)}),
        GetAddress=function()return 6 end,bGeneratorsInitialized=true}
function widget:BindGenerators()
 assert(not self.bGeneratorsInitialized)
 binds=binds+1
 self.FriendlyGenerators.items[#self.FriendlyGenerators.items+1]=icon(g2)
 self.bGeneratorsInitialized=true
end
''')
        lua.globals().refresh = lua.execute(source[start:end] + chr(10) + 'return refresh_generator_icons')
        self.assertTrue(lua.execute('''
refresh(widget,gs,world,1)
assert(widget.FriendlyGenerators:GetChildrenCount()==2 and binds==0)
late=g2; now=5; refresh(widget,gs,world,1)
assert(widget.FriendlyGenerators:GetChildrenCount()==2 and binds==0)
now=5.75; refresh(widget,gs,world,1)
assert(binds==1)
now=6; refresh(widget,gs,world,1)
assert(widget.FriendlyGenerators:GetChildrenCount()==2 and widget.EnemyGenerators:GetChildrenCount()==2)
assert(widget.FriendlyGenerators:GetChildAt(0).CachedActor==g1)
assert(widget.FriendlyGenerators:GetChildAt(1).CachedActor==g2)
now=7; refresh(widget,gs,world,1)
assert(binds==1)
return true
'''))


if __name__ == '__main__':
    unittest.main()
