from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lupa.lua54 import LuaRuntime

from practice import FIELDS
from summarize import summarize


class RecorderTest(unittest.TestCase):
    def test_batches_in_game_samples_with_jet_and_ski_state(self):
        lua = LuaRuntime()
        record = lua.execute(Path(__file__).with_name('record.lua').read_text(encoding='utf-8'))
        exercise = lua.execute("""
return function(record,path)
 local next_tick,now=nil,0
 local jet={InputID=7,InputPressed=false}
 jet.Ability={GetClass=function()
  return {GetFullName=function()
   return 'BlueprintGeneratedClass /Game/Abilities/Devices/Jet_Pack/GA_Jetpack.GA_Jetpack_C'
  end}
 end}
 local pawn={bInitialized=true,CharacterMovement={Velocity={X=10,Y=20,Z=30},bWantsToSki=true,
  IsMovingOnGround=function() return true end}}
 pawn.AbilitySystemComponent={ActivatableAbilities={Items={ForEach=function(_,f)
  f(0,{get=function() return jet end})
 end}}}
 function pawn:GetHealth() return 100 end
 function pawn:GetAddress() return 1 end
 function pawn:GetFullName() return 'pawn' end
 function pawn:K2_GetActorLocation() return {X=11,Y=21,Z=31} end
 function pawn:GetLastMovementInputVector() return {X=1,Y=0} end
 function pawn:GetEnergy() return 55 end
 local pc={Pawn=pawn,PlayerState={r_TeamId=1},IsLocalPlayerController=function() return true end,
  HasAuthority=function() return false end,GetControlRotation=function() return {Yaw=20,Pitch=10} end}
 local gs={GetFullName=function() return 'world' end}
 function StaticFindObject() return {GetTimeSeconds=function() return now end} end
 function ExecuteInGameThreadWithDelay(delay,fn) assert(delay==50);next_tick=fn end
 local messages={}
 record({path=path,world='world',scope=function() end,valid=function(x) return x~=nil end,
  report=function(s) messages[#messages+1]=s end})(pc,gs)
 for n=1,10 do now=now+.05;jet.InputPressed=n>5;next_tick() end
 assert(messages[1]=='BOT_DEMO_RECORDING')
end
""")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'movement.csv'
            path.write_text(FIELDS + '\n', encoding='ascii')
            exercise(record, path.as_posix())
            self.assertEqual(summarize(path), {'samples': 10, 'segments': 1, 'recorded_seconds': .45,
                             'movement_samples': 10, 'ski_samples': 10, 'jet_samples': 5})


if __name__ == '__main__':
    unittest.main()
