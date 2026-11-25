"""Exercise the connected-client Blink cue hooks with local and remote actors."""
import unittest

from lupa.lua54 import LuaRuntime

from test_blink_movement import CLIENT, FIXTURE


PRESENTATION = r'''
local frames, effects, camera = {}, {}, {}
function ExecuteInGameThreadWithDelay(_,callback) frames[#frames+1]=callback end
local function frame()
 time=time+.016
 local queued=frames;frames={}
 for _,callback in ipairs(queued)do callback()end
end
function FName(text)return {ToString=function()return text end}end
local start,ending='GameplayCue.Blink.Start','GameplayCue.Blink.End'
destination={X=2526,Y=2,Z=3}
ability.CurrentStepLocation=destination
pawn.AbilitySystemComponent=entity(false)
function pawn:IsLocallyViewed()return true end
function pawn:GetVelocity()return self.velocity or {X=0,Y=0,Z=0}end
function ability:GetAddress()return self end
function ability:PlayFX(first,finish)
 camera[#camera+1]={first,finish}
 local tag=param({TagName=FName(ending)})
 hooks.K2_ExecuteGameplayCueWithParams(param(self),tag)
 assert(tag:get().TagName:ToString()=='None')
end
local function cue(actor,name,where)
 local tag=param({TagName=FName(name)})
 hooks.NetMulticast_InvokeGameplayCueExecuted_WithParams(param(actor),tag,param({Current=0}),param({Location=where}))
 return tag:get().TagName:ToString()
end
function pawn.AbilitySystemComponent:NetMulticast_InvokeGameplayCueExecuted_WithParams(tag,_,params)
 effects[#effects+1]={cue(self,tag.TagName:ToString(),params.Location),params.Location}
end
local function predict()
 arm();move(pawn,destination,false,true)
end
local function outgoing(name)
 local add,execute=param({TagName=FName(name)}),param({TagName=FName(name)})
 hooks.K2_AddGameplayCueWithParams(param(ability),add)
 hooks.K2_ExecuteGameplayCueWithParams(param(ability),execute)
 return add:get().TagName:ToString(),execute:get().TagName:ToString()
end
local function camera_alpha()
 return afterHooks.GetThirdPersonCameraAlpha(param(pawn))
end
'''


class BlinkPresentationTests(unittest.TestCase):
    def check(self, scenario):
        source = CLIENT.read_text(encoding='utf-8')
        start = source.index('local bind_blink_movement=')
        end = source.index('local function observe_markers', start)
        fixture = FIXTURE.replace('local hooks = {}', 'local hooks,afterHooks = {},{}')
        fixture = fixture.replace(' return 1, 2\n', " afterHooks[path:match('([^:]+)$')] = after\n return 1, 2\n")
        fixture = fixture.replace('local function report(value) error(value) end', 'local function report() end')
        before, after = fixture.split('local function arm()', 1)
        LuaRuntime(unpack_returned_tuples=True).execute(
            before + source[start:end] + 'local function arm()' + after + PRESENTATION + scenario
        )

    def test_host_departure_once_and_arrival_when_movement_catches_up(self):
        self.check('''predict()
        assert(outgoing(start)=='None' and outgoing(ending)=='None')
        assert(camera_alpha()==1 and camera_alpha()==nil)
        assert(cue(pawn.AbilitySystemComponent,start,pawn.origin)==start)
        assert(cue(pawn.AbilitySystemComponent,start,pawn.origin)=='None')
        assert(cue(pawn.AbilitySystemComponent,ending,destination)=='None')
        assert(cue(pawn.AbilitySystemComponent,ending,destination)=='None')
        frame();frame();assert(#effects==0 and #camera==0)
        pawn.origin=destination;frame();frame()
        assert(#effects==1 and effects[1][1]==ending and effects[1][2].X==2526)
        assert(#camera==1 and camera[1][2].X==2526)
        assert(cue(pawn.AbilitySystemComponent,ending,destination)=='None')
        frame();assert(#effects==1 and #camera==1)''')

    def test_rendered_motion_before_host_cue_still_replays_once(self):
        self.check('''predict();frame();local departure=pawn.origin;pawn.origin=destination
        assert(#effects==0 and #camera==0)
        assert(cue(pawn.AbilitySystemComponent,ending,destination)=='None')
        frame();assert(#effects==0)
        assert(cue(pawn.AbilitySystemComponent,start,departure)==start)
        frame();assert(#effects==1 and #camera==1)''')

    def test_refused_or_expired_cast_never_plays_arrival(self):
        self.check('''predict();outgoing(ending);assert(camera_alpha()==1)
        frame();time=time+3;frame()
        assert(#effects==0 and #camera==0 and camera_alpha()==nil)
        predict();assert(cue(pawn.AbilitySystemComponent,start,pawn.origin)==start)
        assert(cue(pawn.AbilitySystemComponent,ending,pawn.origin)=='None')
        frame();assert(#effects==0 and #camera==0)''')

    def test_clipped_cast_uses_hosts_actual_end(self):
        self.check('''predict();frame()
        local clipped={X=1150,Y=2,Z=3}
        cue(pawn.AbilitySystemComponent,start,pawn.origin)
        cue(pawn.AbilitySystemComponent,ending,clipped)
        pawn.origin=clipped;frame()
        assert(#effects==1 and effects[1][2].X==1150 and camera[1][2].X==1150)''')

    def test_ski_momentum_is_not_a_blink_and_does_not_hide_the_visual_landing(self):
        self.check('''pawn.velocity={X=6000,Y=3600,Z=-2600};predict();frame()
        cue(pawn.AbilitySystemComponent,start,pawn.origin)
        cue(pawn.AbilitySystemComponent,ending,destination)
        for i=1,12 do pawn.origin={X=1+96*i,Y=2+58*i,Z=3-42*i};frame() end
        assert(#effects==0 and #camera==0)
        pawn.origin={X=3700,Y=760,Z=-600};frame()
        assert(#effects==1 and effects[1][2].X==3700 and camera[1][2].Y==760)''')

    def test_other_player_and_other_cues_keep_their_presentation(self):
        self.check('''predict()
        assert(outgoing('GameplayCue.Other')=='GameplayCue.Other')
        assert(cue(other,start,pawn.origin)==start)
        assert(cue(other,ending,destination)==ending)
        cue(pawn.AbilitySystemComponent,start,pawn.origin)
        cue(pawn.AbilitySystemComponent,ending,destination)
        pc.Pawn=other
        pawn.origin=destination;frame()
        assert(#effects==0 and #camera==0)''')


if __name__ == '__main__':
    unittest.main()
