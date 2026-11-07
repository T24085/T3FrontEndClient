"""The results Escape fallback defers to the original menu action."""
from pathlib import Path
import re
import unittest

from lupa.lua54 import LuaRuntime

SOURCE = (Path(__file__).resolve().parent / 'lua/client.lua').read_text(encoding='utf-8')


class PostMatchEscapeTests(unittest.TestCase):
    def test_original_result_menu_and_ownership(self):
        lua = LuaRuntime()
        lua.compile(re.sub(r'@@[A-Z_]+@@', '"fixture"', SOURCE))
        start = SOURCE.index('local postMatchEscapeBound=false')
        end = SOURCE.index('local function client_tick(sys)', start)
        setup = '''
local resultPhase='GamePhase.GameplayEndedPhase'
local phase,route,remote,visible=resultPhase,'Result',true,true
local world,foreign,gs,pc,result,class,manager,menu,menuClass={},{},{},{},{},{},{},{},{}
local calls,bindings,reports=0,0,0
local key,hide
local deferred={}
local stopped=false
local function valid(o)return o~=nil end
local function scope()end
local function signature(path,params)assert((path:match(':OnNavigateMenu$') or path:match(':OnHide$')) and #params==0)end
local function report(message)
 if message=='POST_MATCH_ESCAPE_READY' then return end
 assert(message:match('POST_MATCH_ESCAPE_MENU'),message);reports=reports+1
end
local function state()return gs end
local function name(text)return{ToString=function()return text end}end
for i,o in ipairs({world,foreign,gs,pc,result})do
 function o:GetAddress()return i end
 function o:GetFullName()return tostring(i)end
end
function gs:GetWorld()return world end
function gs:HasAuthority()return false end
gs.r_GameplayPhaseInfo={Phase={TagName={ToString=function()return phase end}}}
function pc:IsLocalPlayerController()return true end
function pc:HasAuthority()return not remote end
function pc:GetWorld()return world end
local resultWorld=world
function result:GetWorld()return resultWorld end
function result:GetOwningPlayer()return pc end
function result:GetClass()return class end
function class:GetFullName()
 return 'WidgetBlueprintGeneratedClass /Game/UI/RallyHereUpdates/UI_Scene_Result_Frontier_RH_v2.UI_Scene_Result_Frontier_RH_v2_C'
end
function result:IsVisible()return visible end
function menu:GetClass()return menuClass end
function menuClass:GetFullName()
 return 'WidgetBlueprintGeneratedClass /Game/UI/RallyHereUpdates/Shared/Scenes/UI_Scene_Menu_RH_v2.UI_Scene_Menu_RH_v2_C'
end
menu.GetWorld=result.GetWorld;menu.GetOwningPlayer=result.GetOwningPlayer
function result:IsTopViewRoute()return route=='Result' end
function result:GetViewManager()return manager end
function result:OnNavigateMenu()calls=calls+1;route='StartMenu' end
function manager:GetTopViewRoute()return name(route)end
function FindAllOf()return{result}end
Key={ESCAPE=27}
function StaticFindObject()return {}end
function RegisterHook(_,callback)hide=callback end
function RegisterKeyBind(k,callback)assert(k==27);key=callback;bindings=bindings+1 end
function ExecuteInGameThread(callback)callback()end
function ExecuteInGameThreadWithDelay(delay,callback)
 assert(delay>0);deferred[#deferred+1]=callback
end
local function tick()
 local callback=table.remove(deferred,1)
 if callback then callback() end
end
'''
        exercise = '''
bind_post_match_escape();bind_post_match_escape();assert(bindings==1)
phase='GamePhase.GameplayStartPhase';key();assert(#deferred==0 and calls==0)
phase=resultPhase;resultWorld=foreign;key();assert(#deferred==0 and calls==0)
resultWorld=world;remote=false;key();assert(#deferred==0 and calls==0)
remote=true;visible=false;key();assert(#deferred==0 and calls==0)
visible=true;key();assert(#deferred==1);route='StartMenu';tick();assert(calls==0)
key();assert(#deferred==0 and calls==0)
route='Result';key();key();tick();assert(calls==1 and reports==1 and route=='StartMenu')
hide({get=function()return menu end});route='Result'
key();assert(#deferred==1);tick();assert(calls==1)
route='Result';key();phase='GamePhase.GameplayStartPhase';tick();assert(calls==1)
'''
        lua.execute(setup + SOURCE[start:end] + exercise)
