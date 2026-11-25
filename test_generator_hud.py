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
function valid(o) return o~=nil and not o.invalid end
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
local old=generator(20,2)
old.GetWorld=function()return object(30)end
local invalid=generator(21,1)
invalid.invalid=true
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
function StaticFindObject(path)
 assert(path:match(':OnGeneratorsReady$'))
 return {GetFullName=function()return 'Function '..path end}
end
local function weak(get) return {Get=get} end
now,late,binds=0,nil,0
gs={r_Generators={weak(function()return g1 end),weak(function()return late end),
                  weak(function()return g3 end),weak(function()return g4 end),
                  GetArrayNum=function()return 4 end},
    GetServerWorldTimeSeconds=function()return now end}
local other={GetClass=function()return {GetFullName=function()return 'Unrelated widget'end}end}
originalFriendly,originalEnemy=icon(g1),icon(g3)
widget={FriendlyGenerators=panel({originalFriendly,icon(g1),icon(nil),icon(invalid),other}),
        EnemyGenerators=panel({originalEnemy,icon(g4),icon(old)}),
        GetAddress=function()return 6 end,bGeneratorsInitialized=true}
function widget:OnGeneratorsReady()
 assert(not self.bGeneratorsInitialized)
 binds=binds+1
 for _,actor in ipairs({g1,g2})do table.insert(self.FriendlyGenerators.items,icon(actor))end
 for _,actor in ipairs({g3,g4})do table.insert(self.EnemyGenerators.items,icon(actor))end
 self.bGeneratorsInitialized=true
end
''')
        lua.globals().refresh = lua.execute(source[start:end] + chr(10) + 'return refresh_generator_icons')
        self.assertTrue(lua.execute('''
refresh(widget,gs,world,1)
assert(widget.FriendlyGenerators:GetChildrenCount()==5 and binds==0)
late=g2; now=5; refresh(widget,gs,world,1)
assert(widget.FriendlyGenerators:GetChildrenCount()==4 and binds==0)
now=5.75; refresh(widget,gs,world,1)
assert(binds==1)
assert(widget.FriendlyGenerators:GetChildrenCount()==3 and widget.EnemyGenerators:GetChildrenCount()==2)
assert(widget.FriendlyGenerators:GetChildAt(0)==originalFriendly)
assert(widget.FriendlyGenerators:GetChildAt(1).GetClass():GetFullName()=='Unrelated widget')
assert(widget.FriendlyGenerators:GetChildAt(2).CachedActor==g2)
assert(widget.EnemyGenerators:GetChildAt(0)==originalEnemy)
now=7; refresh(widget,gs,world,1)
assert(binds==1)
return true
'''))


    def test_score_refresh_repairs_hidden_widgets_and_retries_transient_errors(self):
        source = SOURCE.read_text(encoding='utf-8')
        start = source.index('local scoreBarClass')
        end = source.index('-- END_DIRECT_PLAYTEST_PRESENTATION', start)
        lua = LuaRuntime()
        lua.globals().refresh = lua.execute(source[start:end] + chr(10) + 'return refresh_ctf_score_bar')
        self.assertTrue(lua.execute('''
function valid(value) return value~=nil end
local failures=0
function report(message)
 if message:find('CTF_SCORE_BAR_ERROR',1,true) then failures=failures+1 end
end
local world={GetAddress=function()return 1 end}
local controller={GetAddress=function()return 2 end,GetWorld=function()return world end}
local team={r_TeamId=1}
local missing=true
local scores={{TeamNum=1,Score=3},{TeamNum=2,Score=5}}
local state={GetWorld=function()return world end,GetAddress=function()return 3 end}
function state:GetServerWorldTimeSeconds() return 0 end
state.r_CurrentTeamScores={
 GetArrayNum=function() return #scores end,
 ForEach=function(_,visit)
  for i,row in ipairs(scores) do visit(i,{get=function()return row end}) end
 end,
}
local function counter()
 local c={CachedScore=0}
 c.ScoreText={GetText=function()return {ToString=function()return tostring(c.CachedScore) end} end}
 return c
end
local first,second=counter(),counter()
local widget={
 FriendlyScoreFill={},EnemyScoreFill={},UI_Game_Scorebar_ScoreCount=first,
 UI_Game_Scorebar_ScoreCount_1=second,
 GetWorld=function()return world end,GetOwningPlayer=function()return controller end,
 GetClass=function()return {GetFullName=function()
  return 'WidgetBlueprintGeneratedClass /Game/UI/Components/Game/WBP_Game_ScoreBar_CTF.WBP_Game_ScoreBar_CTF_C'
 end}end,
 IsVisible=function()return false end,
}
function widget:UpdateScore(score,_,count)
 if missing and count==first then error('counter binding still loading') end
 count.CachedScore=score
end
function FindAllOf()return {widget} end
refresh(controller,team,state)
assert(first.CachedScore==0 and second.CachedScore==5 and failures==1)
refresh(controller,team,state)
assert(failures==1)
missing=false
refresh(controller,team,state)
assert(first.CachedScore==3 and second.CachedScore==5)
scores[1].Score=0
scores[2].Score=1
refresh(controller,team,state)
assert(first.CachedScore==0 and second.CachedScore==1)
return true
'''))



if __name__ == '__main__':
    unittest.main()
