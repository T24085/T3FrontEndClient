from pathlib import Path
import re
import unittest

from lupa.lua54 import LuaRuntime


CLIENT = Path(__file__).resolve().parent / "lua/client.lua"
FIXTURE = r'''
local function valid(value) return value and value.valid end
local function report(value) error(value) end
local function signature() end
local hooks = {}
function RegisterHook(path, before, after)
 hooks[path:match('([^:]+)$')] = before
 return 1, 2
end
local time = 5
os.clock = function() return time end
local function loaded() return {GetTimeSeconds=function() return time end} end
local function entity(authority)
 local object = { valid=true, authority=authority, origin={X=1,Y=2,Z=3} }
 function object:HasAuthority() return self.authority end
 function object:GetAddress() return self end
 function object:K2_GetActorLocation() return self.origin end
 return object
end
local pawn,other,pc = entity(false),entity(false),entity(false)
pc.Pawn,pawn.Controller = pawn,pc
function pc:IsLocalPlayerController() return true end
local destination={X=25,Y=26,Z=27}
local ability={valid=true,CharCached=pawn,CurrentStepLocation=destination,
 kind='BlueprintGeneratedClass /Game/Topaz/Abilities/Packs/Blink/GA_Pack_Blink.GA_Pack_Blink_C'}
function ability:GetClass() return {GetFullName=function()return self.kind end} end
function ability:K2_HasAuthority() return self.CharCached.authority end
function ability:GetAvatarActorFromActorInfo() return self.CharCached end
local function param(value)
 return {get=function(self)return self.value end,set=function(self,new)self.value=new end,value=value}
end
local function arm()
 bind_blink_movement(pc)
 hooks.K2_CommitAbility(param(ability))
end
local function move(actor,target,sweep,teleport)
 local location,flag = param(target),param(teleport)
 hooks.K2_SetActorLocation(param(actor),location,param(sweep),nil,flag)
 return location:get(),flag:get()
end
'''


class BlinkPredictionTests(unittest.TestCase):
    def setUp(self):
        source = CLIENT.read_text(encoding='utf-8')
        self.runtime = LuaRuntime(unpack_returned_tuples=True)
        self.runtime.compile(re.sub(r'@@[A-Z0-9_]+@@', '"fixture"', source))
        self.source = source[source.index('local bind_blink_movement='):source.index('local function observe_markers')]
        fixture, cases = FIXTURE.split('local function arm()', 1)
        self.fixture = fixture + self.source + 'local function arm()' + cases

    def check(self, script):
        self.runtime.execute(self.fixture + script)

    def test_only_matching_blink_move_is_held(self):
        self.check('''arm()
        local p,flag=move(pawn,destination,false,true)
        assert(p.X==1 and p.Y==2 and p.Z==3 and not flag)
        p,flag=move(pawn,destination,false,true)
        assert(p.X==25 and flag)''')

    def test_other_actor_and_move_do_not_consume_blink(self):
        self.check('''arm()
        assert(move(other,destination,false,true).X==25)
        assert(move(pawn,{X=30,Y=26,Z=27},false,true).X==30)
        assert(move(pawn,destination,true,true).X==25)
        assert(move(pawn,destination,false,false).X==25)
        assert(move(pawn,destination,false,true).X==1)''')

    def test_authority_and_other_abilities_are_unchanged(self):
        self.check('''pawn.authority=true; arm()
        assert(move(pawn,destination,false,true).X==25)
        pawn.authority=false; ability.kind='other'; arm()
        assert(move(pawn,destination,false,true).X==25)''')

    def test_replaced_pawn_and_expired_context_are_unchanged(self):
        self.check('''arm();pc.Pawn=other
        assert(move(pawn,destination,false,true).X==25)
        pc.Pawn=pawn;arm();time=time+.11
        assert(move(pawn,destination,false,true).X==25)''')


if __name__ == '__main__':
    unittest.main()
