from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime


class BaseLightingTests(unittest.TestCase):
    def test_tagged_lights_follow_replicated_team_power(self):
        source = (Path(__file__).parent / 'lua/client.lua').read_text(encoding='utf8')
        start = source.index('local configure_base_lighting=(function()')
        end = source.index('local configure_water=', start)
        LuaRuntime().execute('''
local world={GetAddress=function()return 1 end}
local wrong={GetAddress=function()return 2 end}
local actors,reports={},{}
local scans=0
local valid=function(object)return object~=nil end
local report=function(line)reports[#reports+1]=line end
local mapDefinitions={OptOut={world='/Game/OptOut.Test:',emergency_lighting=false}}
FName=function(name)return name end
FindAllOf=function(class)assert(class=='Actor');scans=scans+1;return actors end
local function light(tag,owner,map)
 local body={SetVisibility=function(self,on)self.visible=on end}
 local actor={LightComponent=body,GetWorld=function()return owner or world end,
              GetFullName=function()return 'PointLight /Game/'..(map or 'Test')..'.Test:PersistentLevel.Lamp' end,
              ActorHasTag=function(_,name)return name==tag end,
              SetActorHiddenInGame=function(self,hidden)self.hidden=hidden end}
 actors[#actors+1]=actor
 return actor
end
local function generator(team,id)
 return {r_TeamId=team,online=true,GetWorld=function()return world end,GetAddress=function()return id end,
         IsOnline=function(self)return self.online end}
end
local function weak(actor)return {Get=function()return actor end} end
local function state(map,refs)
 return {GetWorld=function()return world end,GetAddress=function()return map end,
         GetFullName=function()return 'GameState /Game/'..map..'.Test:PersistentLevel.GS' end,r_Generators=refs}
end
''' + source[start:end] + '''
local n1,a1=light('CwPwr_T1_Normal'),light('CwPwr_T1_Alarm')
local n2,a2=light('CwPwr_T2_Normal'),light('CwPwr_T2_Alarm')
local always=light('Amber')
local foreign=light('CwPwr_T1_Normal',wrong)
local first,second,opponent=generator(1,101),generator(1,102),generator(2,103)
local refs={weak(first),weak(second),weak(opponent),GetArrayNum=function(self)return #self end}
local match=state('Test',refs)
configure_base_lighting(match)
assert(n1.LightComponent.visible and not a1.LightComponent.visible and n2.LightComponent.visible and not a2.LightComponent.visible)
first.online=false
configure_base_lighting(match)
assert(n1.LightComponent.visible and #reports==2)
second.online=false
configure_base_lighting(match)
assert(n1.hidden and not n1.LightComponent.visible and not a1.hidden and a1.LightComponent.visible)
assert(n2.LightComponent.visible and not a2.LightComponent.visible and #reports==3)
second.online=true
configure_base_lighting(match)
assert(n1.LightComponent.visible and not a1.LightComponent.visible and #reports==4 and scans==1)
assert(always.hidden==nil and foreign.hidden==nil)
local ln,la=light('CwPwr_T1_Normal',nil,'Late'),light('CwPwr_T1_Alarm',nil,'Late')
second.online=false
refs[2]=weak(nil)
local late=state('Late',refs)
configure_base_lighting(late)
assert(ln.hidden==nil and la.hidden==nil)
refs[2]=weak(second)
configure_base_lighting(late)
assert(ln.hidden and not la.hidden)
local zn,za=light('CwPwr_T1_Normal',nil,'Zero'),light('CwPwr_T1_Alarm',nil,'Zero')
configure_base_lighting(state('Zero',{GetArrayNum=function()return 0 end}))
assert(zn.LightComponent.visible and not za.LightComponent.visible)
configure_base_lighting(state('OldMap',nil))
configure_base_lighting(state('OptOut',nil))
assert(scans==4)
''')
