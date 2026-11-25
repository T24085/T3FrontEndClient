from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lupa.lua54 import LuaRuntime

from flight_training import FlightTrainer, WALK, assignments, choose_profile, flight_comparison, measure_flight
from team_waves import wave_plan


class FlightTrainingTest(unittest.TestCase):
    def test_hill_survey_rejects_flat_or_discontinuous_terrain(self):
        lua = LuaRuntime()
        choose = lua.execute(Path(__file__).with_name('hill_course.lua').read_text(encoding='utf-8'))['choose']
        origin = lua.table(X=0,Y=0,Z=2000)
        self.assertIsNone(choose(origin,lambda *_: 2000,lambda _: True))
        self.assertIsNone(choose(origin,lambda x,y,z: 2000 if abs(x)<1 and abs(y)<1 else 500,lambda _: True))
        course = choose(origin,lambda x,y,_: 2000-.20*x,lambda point: point.X>6500)
        self.assertAlmostEqual(course.drop,1600,delta=95)
        self.assertAlmostEqual(course.last.Z,2000-.20*course.last.X)

    def test_drills_measure_momentum_and_jet_progress_instead_of_rewarding_vertical_only_flight(self):
        header = 'seconds,forward_m,vx_cm_s,vy_cm_s,grounded,jet,ski,energy,x_cm,y_cm,z_cm,heading_deg,course_drop_m,cross_m\n'
        with TemporaryDirectory() as tmp:
            trace = Path(tmp)/'trace.csv'
            downhill = ['0,0,0,0,1,0,0,100,0,0,2000,0,16,0',
                        '.25,20,1200,0,1,0,1,100,2000,0,1600,0,16,0',
                        '.5,80,1400,0,1,0,1,100,8000,0,400,0,16,0']
            trace.write_text(header+'\n'.join(downhill)+'\n')
            result = measure_flight(trace,'downhill')
            self.assertTrue(result['finished'])
            self.assertEqual(result['entry_kmh'],43.2)
            self.assertEqual(result['exit_kmh'],50.4)
            self.assertEqual(result['retention'],1.167)
            uphill = ['0,0,0,0,1,0,0,100,0,0,400,0,16,0',
                      '.25,0,0,0,0,1,0,92,0,0,2000,0,16,0',
                      '.5,80,1400,0,0,1,0,83,8000,0,2400,0,16,0']
            trace.write_text(header+'\n'.join(uphill)+'\n')
            result = measure_flight(trace,'uphill')
            self.assertTrue(result['finished'])
            self.assertEqual(result['elevation_gain_m'],20)
            self.assertEqual(result['jet_forward_m'],27.5)
            self.assertNotIn('run-only',assignments(1,10,'steady-jets',1,'uphill'))
            self.assertIn('ski-only',assignments(1,10,'steady-jets',1,'uphill'))
            self.assertNotIn('steady-jets',assignments(0,10,None,1,'downhill'))

    def test_training_covers_profiles_and_evaluation_crosses_over_the_same_lanes(self):
        first = assignments(0, 10, None, 1)
        self.assertEqual(first[:5], first[5:])
        self.assertEqual(len(set(first)), 5)
        candidate = 'short-jets'
        a, b = (assignments(index, 10, candidate, 1) for index in (1, 2))
        self.assertTrue(all({x, y} == {WALK, candidate} for x, y in zip(a, b, strict=True)))
        trained = FlightTrainer(a, 30, candidate)
        plan = LuaRuntime().execute(wave_plan(trained, 2))
        self.assertEqual(plan['flight_plan'][1]['pulse'], 0)
        self.assertEqual(plan['flight_plan'][2]['pulse'], .4)

    def test_new_drills_only_assign_ski_and_jet_or_continuous_downhill_ski(self):
        for course in ('straight', 'downhill', 'uphill'):
            selection = assignments(0, 12, None, 1, course, strict=True)
            self.assertNotIn(WALK, selection)
            self.assertNotIn('ski-delayed', selection)
            self.assertEqual(selection[:6], selection[6:])
            trainer = FlightTrainer(selection, 30, None, course, strict=True)
            self.assertTrue(all(plan['ski'] == 1 and (plan['pulse'] > 0) == (course != 'downhill')
                                for plan in trainer.flight_plan.values()))

    def test_comparison_requires_actual_jet_flight_and_a_speed_gain_on_each_side(self):
        candidate = 'steady-jets'

        def trial(index, team, profile):
            return dict(bot=index, team=team, profile=profile, start_cm=(index, 0, 0), heading_deg=0, score=.7 if profile == candidate else .25,
                        median_kmh=45 if profile == candidate else 11, airborne_m=54 if profile == candidate else 0,
                        jet_seconds=3 if profile == candidate else 0)

        waves = [
            {'bots': [trial(index, team, profile) for index, team, profile in zip(
                range(1, 5), (1, 1, 2, 2), assignments(wave, 4, candidate, 1), strict=True)]}
            for wave in (1, 2)
        ]
        self.assertEqual(choose_profile(waves), candidate)
        self.assertTrue(flight_comparison(waves, candidate)['qualified'])
        waves[1]['bots'][0]['start_cm'] = (501, 0, 0)
        self.assertFalse(flight_comparison(waves, candidate)['qualified'])
        waves[1]['bots'][0]['start_cm'] = (1, 0, 0)
        for wave in waves:
            for row in wave['bots']:
                if row['team'] == 2 and row['profile'] == candidate:
                    row['median_kmh'] = 11
        self.assertFalse(flight_comparison(waves, candidate)['qualified'])
        for wave in waves:
            for row in wave['bots']:
                if row['team'] == 2 and row['profile'] == candidate:
                    row['jet_seconds'] = 0
        self.assertIsNone(choose_profile(waves))

    def test_trace_separates_forward_flight_from_low_speed_running(self):
        header = 'seconds,forward_m,vx_cm_s,vy_cm_s,grounded,jet,ski,energy,x_cm,y_cm,z_cm,heading_deg\n'
        with TemporaryDirectory() as tmp:
            trace = Path(tmp)/'trace.csv'
            trace.write_text(header + '0,0,0,0,1,0,0,100,0,0,0,0\n.25,.6,300,0,1,0,0,100,60,0,0,0\n'
                             '.5,2.5,1100,0,0,1,1,91,250,0,20,0\n.75,6,1500,0,0,1,1,89,600,0,40,0\n'
                             '1,10,1600,0,0,1,1,86,1000,0,40,0\n1.25,13,900,0,1,0,1,85,1300,0,0,0\n')
            result = measure_flight(trace)
            strict = measure_flight(trace, strict=True)
        self.assertEqual(result['forward_m'], 13)
        self.assertEqual(result['airborne_m'], 7.5)
        self.assertEqual(result['airborne_seconds'], .5)
        self.assertEqual(result['slow_seconds'], .5)
        self.assertEqual(result['jet_seconds'], .75)
        self.assertGreater(result['median_kmh'], 30)
        self.assertEqual(strict['ground_jog_seconds'], .25)
        self.assertEqual(strict['ground_jog_ratio'], .20)
        self.assertEqual(strict['score'], 0)

    def test_lua_drill_uses_native_input_commands_and_restores_flag_activation(self):
        lua = LuaRuntime()
        factory = lua.execute(Path(__file__).with_name('flight_trials.lua').read_text(encoding='utf-8'))
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            exercise = lua.eval("""function(factory, path, strict)
                local t, next_frame, restored, commands = 0,nil,false,{}
                local world = {GetAddress=function() return 2 end}
                local flag = {r_bPickupActive=true, GetWorld=function() return world end, GetOwner=function() end,
                    SetPickupActive=function(self,on) self.r_bPickupActive=on; restored=on end}
                local clock = {GetTimeSeconds=function() return t end}
                FName = function(name) return name end
                EngineTickAvailable = true
                StaticFindObject = function(name)
                    if name:find('GameplayStatics',1,true) then return clock end
                    return {SendGameplayEventToActor=function(_,pawn) pawn.CharacterMovement.bIsJetpackActive=false end}
                end
                FindAllOf = function(name) assert(name=='TopPickup_Flag'); return {flag} end
                ExecuteInGameThreadAfterFrames = function(_,fn) next_frame=fn end
                local function bot(team)
                    local pos = {X=0,Y=0,Z=0}
                    local pawn = {PlayerState={bIsABot=true}, CapsuleComponent={IgnoreActorWhenMoving=function() end}}
                    local move = {Velocity={X=0,Y=0,Z=0},bIsJetpackActive=false,
                        IsMovingOnGround=function(self) return not self.bIsJetpackActive end,
                        SetWantsToSki=function(self,on) self.ski=on end,
                        IsSkiing=function(self) return self.ski end, StopMovementImmediately=function() end}
                    pawn.CharacterMovement=move
                    pawn.AbilitySystemComponent={TryActivateAbility=function()
                        move.bIsJetpackActive=true; commands[team]=true; return true
                    end}
                    pawn.GetTeamId=function() return team end
                    pawn.GetHealth=function() return 100 end
                    pawn.GetEnergy=function() return 100 end
                    pawn.GetAddress=function() return team+10 end
                    pawn.GetWorld=function() return world end
                    pawn.HasAuthority=function() return true end
                    pawn.GetEquippedAbility=function() return {Handle=1} end
                    pawn.K2_GetActorLocation=function() return pos end
                    pawn.AddMovementInput=function(_,axis)
                        if strict then assert(move.ski,'moved before skis were enabled') end
                        pos.X=pos.X+axis.X*20
                        move.Velocity.X=300
                    end
                    local brain={IsRunning=function() return true end,StopLogic=function() end}
                    return {team=team,pawn=pawn,training_facing={Yaw=0}, controller={Pawn=pawn,
                            GetStateTreeComponent=function() return brain end}}
                end
                local env={valid=function(obj) return obj~=nil end, scope=function() end, signature=function() end,
                    report=function(msg) assert(not msg:find('ERROR',1,true),msg) end,
                    blue=1,red=1,wave=1,seconds=1.6,course_m=160,path=path,strict_flight=strict,
                    flight_plan={{ski=strict and 1 or 0,pulse=strict and .4 or 0,period=2},{ski=1,pulse=.7,period=2}}}
                factory(env)({HasAuthority=function() return true end,GetWorld=function() return world end},{},{bot(1),bot(2)})
                assert(not flag.r_bPickupActive)
                for i=1,10 do
                    local tick=next_frame
                    if not tick then break end
                    next_frame=nil;t=i*.2;tick()
                    if strict and i==1 then assert(commands[1] and commands[2]) end
                end
                assert(restored and env.wave_finished and (not not commands[1])==strict and commands[2])
            end""")
            exercise(factory, root.as_posix(), False)
            self.assertEqual((root/'flight-complete.csv').read_text().strip(), '1,2')
            self.assertGreater(measure_flight(root/'team-bot-2-trace.csv')['jet_seconds'], 0)
            strict_root = root/'strict'
            strict_root.mkdir()
            exercise(factory, strict_root.as_posix(), True)
            self.assertEqual(measure_flight(strict_root/'team-bot-1-trace.csv', strict=True)['ground_jog_seconds'], 0)
