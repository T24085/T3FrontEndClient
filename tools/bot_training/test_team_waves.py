import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lupa.lua54 import LuaRuntime

from practice import TrainingPaused
from team_waves import ready_receipt, run_waves, validate_reset, wave_plan


class TeamWavesTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.out = Path(directory.name)
        self.saved = []

    def trainer(self, waves=2):
        trainer = SimpleNamespace(roster=((1, 'Capper'),), waves_per_launch=waves,
                                  guided={}, defense_tactics={}, offense_tactics={}, aim_boosts={})
        trainer.read_match = lambda *args: setattr(trainer, 'result', dict(learned=len(self.saved)))
        trainer.next_match = lambda: self.trainer(1)
        trainer.save_match = lambda current: self.saved.append(dict(current.result))
        return trainer

    def test_saved_wave_teaches_next_plan_and_traces_do_not_overwrite(self):
        trainer = self.trainer()
        run_waves(trainer, self.out, None)
        self.assertEqual([row['learned'] for row in self.saved], [0, 1])
        self.assertEqual([row['session_wave'] for row in self.saved], [1, 2])
        self.assertEqual([row['verified_reuse'] for row in self.saved], [False, True])
        plan = LuaRuntime().execute((self.out/'team-next-2.lua').read_text())
        self.assertEqual(plan['wave'], 2)

    def test_pause_is_durable_before_next_wave_command(self):
        trainer = self.trainer()
        with patch('team_waves.check_between_matches', side_effect=[None, TrainingPaused()]):
            with self.assertRaises(TrainingPaused):
                run_waves(trainer, self.out, None)
        self.assertEqual(len(self.saved), 1)
        self.assertEqual(trainer.completed_waves, 1)
        self.assertFalse((self.out/'team-next-2.lua').exists())

    def test_obstructed_spawn_row_advances_to_alternate_positions(self):
        lua = LuaRuntime()
        candidate = lua.execute(Path(__file__).with_name('team_spawn.lua').read_text())
        start = lua.eval('''{
            K2_GetActorLocation=function() return {X=100,Y=200,Z=300} end,
            K2_GetActorRotation=function() return {Yaw=90} end
        }''')
        first, first_fallback = candidate(start, 4, 2, 0)
        second, second_fallback = candidate(start, 4, 2, 1)
        self.assertEqual((first.Y, first.Z, first_fallback), (1400, 1300, None))
        self.assertEqual((second.Y, second.Z, second_fallback), (1400, 1300, None))
        lifted, lifted_fallback = candidate(start, 4, 2, 2)
        side, side_fallback = candidate(start, 4, 2, 6)
        self.assertEqual((lifted.X, lifted.Y, lifted.Z, lifted_fallback), (100, 200, 400, 1))
        self.assertAlmostEqual(side.X, -150)
        self.assertAlmostEqual(side.Y, 200)
        self.assertEqual((side.Z, side_fallback), (460, 3))

    def test_spawn_requires_a_walkable_surface_below_the_candidate(self):
        lua = LuaRuntime()
        factory = lua.execute(Path(__file__).with_name('team_spawn_floor.lua').read_text())
        result = lua.eval('''function(factory)
            local post, hit
            local system={GetAddress=function() return 1 end}
            local start={GetAddress=function() return 2 end}
            local function param(value) return {get=function() return value end} end
            StaticFindObject=function() return system end
            RegisterHook=function(_,_,func) post=func end
            function system:LineTraceSingleForObjects(context,top,bottom)
                assert(context==start and top.X==bottom.X and top.Y==bottom.Y and top.Z-bottom.Z==1800)
                post(param(self),param(hit~=nil),param(start),nil,nil,nil,nil,nil,nil,param(hit))
                return hit~=nil
            end
            local query=factory(function(object) return object==system end,function() end)
            local position={X=100,Y=200,Z=400}
            assert(not query(start,position))
            hit={bBlockingHit=true,bStartPenetrating=false,ImpactNormal={Z=.3}}
            assert(not query(start,position))
            hit.ImpactNormal.Z=1
            assert(query(start,position))
            hit.bStartPenetrating=true
            assert(not query(start,position))
            return true
        end''')(factory)
        self.assertTrue(result)

    def test_changed_lineup_requires_another_launch(self):
        trainer = self.trainer()
        alternate = self.trainer(1)
        alternate.roster = ((1, 'Heavy offense'),)
        trainer.next_match = lambda: alternate
        run_waves(trainer, self.out, None)
        self.assertEqual(len(self.saved), 1)
        self.assertFalse((self.out/'team-next-2.lua').exists())

    def test_reset_receipt_is_required_and_bound_to_wave_and_roster(self):
        trainer = self.trainer()
        for value in ('1,1\n', '2,14\n', '1\n', None):
            trainer.wait = lambda *args: value
            with self.assertRaisesRegex(RuntimeError, 'missing_team_reset_receipt'):
                ready_receipt(trainer, self.out, None, 2)
        trainer.wait = lambda *args: '2,1\n'
        self.reset_files()
        ready_receipt(trainer, self.out, None, 2)

    def reset_files(self, second='1,0,0,0,100,100,100,0,0,0'):
        header = 'bot,x_cm,y_cm,z_cm,health,max_health,energy,vx_cm_s,vy_cm_s,vz_cm_s\n'
        (self.out/'team-reset-1.csv').write_text(header+'1,0,0,0,100,100,100,0,0,0\n')
        (self.out/'team-reset-2.csv').write_text(header+second+'\n')

    def test_changed_position_or_resources_cannot_count_as_reuse(self):
        for second in ('1,200,0,0,100,100,100,0,0,0', '1,0,0,0,90,100,100,0,0,0',
                       '1,0,0,0,100,100,20,0,0,0', '1,0,0,0,100,100,100,1000,0,0'):
            self.reset_files(second)
            with self.assertRaisesRegex(RuntimeError, 'training_reuse_unverified'):
                validate_reset(self.out, 2, 1)

    def test_generated_route_command_preserves_exploration_and_tactics(self):
        trainer = self.trainer()
        trainer.guided = {1: dict(approach_route='Side route', layout='flank', pass_runup_cm=9500,
            guidance=4, policy=dict(flank=-1, pulse=.25, period=1.8, ski=1, turn=0, approach_cm=2800))}
        trainer.defense_tactics = {2: ('Heavy on flag', 'baseline')}
        trainer.aim_boosts = {2: 20}
        plan = LuaRuntime().execute(wave_plan(trainer, 3))
        self.assertEqual(plan['guided'][1]['layout'], 'flank')
        self.assertEqual(plan['guided'][1]['runup'], 9500)
        self.assertEqual(plan['defense_tactics'][2]['handoff'], 1600)
        self.assertEqual((plan['aim_boosts'][1], plan['aim_boosts'][2]), (None, 20))

    def test_solo_reset_factory_accepts_no_defenders(self):
        lua = LuaRuntime()
        factory = lua.execute(Path(__file__).with_name('verify_trial_reset.lua').read_text())
        verifier = factory(lua.table(valid=lambda actor: actor is not None), lua.table(), lua.table())
        self.assertTrue(callable(verifier))

    def test_native_reset_replaces_bots_and_rejects_changed_map(self):
        lua = LuaRuntime()
        factory = lua.execute(Path(__file__).with_name('team_wave_reset.lua').read_text())
        lua.eval('''function(factory)
            local function actor(id)
                local a={live=true,id=id}
                a.IsValid=function(self) return self.live end
                a.GetAddress=function(self) return self.id end
                a.HasAuthority=function() return true end
                a.GetFullName=function(self) return 'actor-'..self.id end
                a.GetHealth=function(self) return self.health or 100 end
                a.GetHealthMax=function() return 100 end
                a.GetEnergy=function() return 100 end
                a.K2_DestroyActor=function(self) self.live=false end
                a.K2_TeleportTo=function() return true end
                a.K2_GetActorLocation=function() return {X=0,Y=0,Z=100} end
                a.K2_SetActorLocation=function() return true end
                a.SetActorEnableCollision=function(self,value) self.collision=value end
                a.GetActorEnableCollision=function(self) return self.collision end
                return a
            end
            local world=actor(10)
            local local_player_class=actor(109)
            StaticFindObject=function(path)
                if path:find(':IsValid',1,true) then return function(_,a) return a and a.live~=false end end
                if path=='/Script/Engine.LocalPlayer' then return local_player_class end
                return {}
            end
            local gen=actor(11);gen.GetWorld=function() return world end
            local transient=actor(12)
            transient.live=false
            transient.GetWorld=gen.GetWorld
            transient.GetClass=function() return {GetFullName=function() return 'Pending pickup' end} end
            local function death_drop(id, owner_world)
                local drop=actor(id)
                drop.GetWorld=function() return owner_world end
                drop.GetClass=function() return {
                    GetFullName=function() return 'BlueprintGeneratedClass BP_TopPickup_PlayerAllDrop_C' end,
                    GetFName=function() return {ToString=function() return 'BP_TopPickup_PlayerAllDrop_C' end} end,
                } end
                return drop
            end
            local original=death_drop(13,world)
            local dropped=death_drop(14,world);dropped.live=false
            local foreign=death_drop(15,actor(99))
            local human=actor(16);human.live=false;human.GetWorld=gen.GetWorld
            local empty=actor(17);empty.GetWorld=gen.GetWorld
            local connection,pawn_only=actor(18),actor(19)
            human.IsLocalPlayerController=function() return false end
            connection.GetClass=function() return {GetFName=function()
                return {ToString=function() return 'IpConnection' end}
            end} end
            empty.Player=actor(110)
            empty.Player.IsA=function(_,class) return class==local_player_class end
            empty.IsLocalPlayerController=function() return true end
            local now=0
            os.time=function() return now end
            local stands={{TeamNum=1},{TeamNum=2}}
            for _,s in ipairs(stands) do
                s.HasAuthority=function() return true end;s.IsValid=function() return true end
                s.GetWorld=function() return world end;s.IsFlagAtHome=function() return true end
            end
            local function entry(id)
                local pawn,c,ps=actor(id),actor(id+1),actor(id+2)
                pawn.GetWorld=function() return world end;c.GetWorld=pawn.GetWorld
                pawn.CharacterMovement={Velocity={X=0,Y=0,Z=0},StopMovementImmediately=function() end,
                    SetWantsToSki=function() end,IsMovingOnGround=function() return true end}
                local tree={StopLogic=function() end,IsRunning=function() return true end}
                c.Pawn=pawn;c.PlayerState=ps;c.StopMovement=function() end
                c.GetStateTreeComponent=function() return tree end
                c.SetControlRotation=function() end;c.StartStateTree=function() end
                c.UnPossess=function(self) self.Pawn=nil end
                c.SetLifeSpan=function(self) self.live=false;ps.live=false end
                return {controller=c,pawn=pawn,bot=pawn,training_spawn={},training_facing={}}
            end
            FindAllOf=function(name)
                if name=='TopFlagStand' then return stands end
                if name=='TopGenerator' then return {gen} end
                if name=='Actor' then return {transient, original, dropped, foreign} end
                if name=='ValPlayerController' then return {empty,human} end
                return {}
            end
            local gm={MatchTimer=900,bPausedTimer=false,GetWorld=function() return world end,
                GetMatchState=function() return {ToString=function() return 'InProgress' end} end,
                GetMatchTimer=function(self) return self.MatchTimer end}
            local scores={{TeamNum=1,Score=0},{TeamNum=2,Score=0}}
            local gs={r_GameplayPhaseInfo={Phase={TagName={ToString=function() return 'Gameplay' end}}},
                r_CurrentTeamScores={ForEach=function(_,fn)
                    for i,row in ipairs(scores) do fn(i,{get=function() return row end}) end
                end}}
            gs.GetServerWorldTimeSeconds=function() return 0 end
            gs.GetPhaseRemainingTimer=function(self) return self.r_GameplayPhaseInfo.PhaseTimeRemaining or 900 end
            local receipt
            local service=factory({valid=function(a) return a and a.live~=false end,
                signature=function() end,scope=function() end,report=function(value) receipt=value end})
            local first={entry(20)}
            local stops=0
            first[1].pawn.CharacterMovement.StopMovementImmediately=function() stops=stops+1 end
            service.hold(first[1])
            service.hold(first[1])
            assert(stops==1)
            assert(first[1].state_tree_requested and first[1].pawn.bCanBeDamaged==false)
            assert(service.ready(first))
            service.start(gm,gs,first,1)
            scores[1].Score=1;gm.MatchTimer=600
            transient.live=true;dropped.live=true
            assert(not service.reset(gm,gs,first))
            assert(dropped.live)
            transient.live=false
            now=now+1
            assert(not service.reset(gm,gs,first))
            assert(not dropped.live and original.live and foreign.live)
            now=now+1
            assert(service.reset(gm,gs,first))
            assert(not first[1].pawn.live and not first[1].controller.live)
            local stale={entry(20)}
            local allowed,reason=pcall(service.start,gm,gs,stale,2)
            assert(not allowed and reason:find('retired_pawn_identity',1,true))
            local second={entry(20)}
            second[1].pawn.GetFullName=function() return 'actor-20-recreated' end
            service.start(gm,gs,second,2)
            assert(receipt:find('reused_addresses=1',1,true))
            assert(scores[1].Score==0 and gm.MatchTimer==900 and not gm.bPausedTimer)
            human.live=true;human.Player=connection;dropped.live=true
            assert(not service.reset(gm,gs,second))
            assert(dropped.live)
            human.Player=nil;human.Pawn=pawn_only
            now=now+1
            assert(not service.reset(gm,gs,second))
            assert(dropped.live)
            human.live=false
            now=now+1
            assert(not service.reset(gm,gs,second))
            assert(not dropped.live and original.live and foreign.live)
            now=now+1
            assert(service.reset(gm,gs,second))
            local third={entry(40)}
            service.start(gm,gs,third,3)
            gen.health=90
            local ok,why=pcall(service.reset,gm,gs,third)
            assert(not ok and why:find('map_equipment_changed',1,true))
        end''')(factory)


if __name__ == '__main__':
    unittest.main()
