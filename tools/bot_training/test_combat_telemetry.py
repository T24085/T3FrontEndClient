"""Exercise attribution without turning collision or unrelated health loss into damage."""
import csv
from pathlib import Path
import unittest

from lupa.lua54 import LuaRuntime
from aim_learning import AIM_EVIDENCE_VERSION, assess_trial, benchmark_aim_report, calibration_report, trial_assignment


class CombatTelemetryTest(unittest.TestCase):
    def test_exact_native_effect_context_and_independent_contact(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        source = Path(__file__).resolve().parent
        lua.globals().make_observer = lua.execute((source/'combat_telemetry.lua').read_text(encoding='utf-8'))
        lua.globals().effect_script = (source/'combat_effects.lua').as_posix()
        lua.globals().opaque = object()
        rows, complete, aim, plan = lua.execute(r"""
            local hooks = {}
            local next_frame
            function ExecuteInGameThreadAfterFrames(_,callback) next_frame=callback end
            local function value(x) return function() return x end end
            local function param(x) return {get=value(x)} end
            function RegisterHook(path, pre, post) hooks[path]={pre=pre,post=post};return 1,2 end
            function UnregisterHook(path) hooks[path]=nil end
            FName = function(name) return name end
            local world={GetAddress=value(100)}
            local gm={GetWorld=value(world)}
            local clock={GetTimeSeconds=value(5)}
            local function actor(id, x)
                local object={hp=100,AbilitySystemComponent={GetAddress=value(id+10)},
                    GetAddress=value(id),GetWorld=value(world),GetHealth=function(self) return self.hp end,
                    K2_GetActorLocation=value({X=x,Y=0,Z=0}), CharacterMovement={IsMovingOnGround=value(true)}}
                return object
            end
            local shooter, enemy, ally = actor(1,0), actor(2,1100), actor(3,800)
            shooter.CharacterMovement.IsMovingOnGround=value(false)
            local shot = actor(4,0)
            shot.Instigator=shooter;shot.HasAuthority=value(true);shot.GetFullName=value('Shot 1')
            shot.GetClass=value({GetFName=value({ToString=value('Spinfusor')})})
            shot.GetVelocity=value({X=1000,Y=1000,Z=0})
            shot.HitTargets={Contains=value(false)}
            local causer, instigator, magnitude = shooter, shooter, -70
            local context_path='/Script/GameplayAbilities.AbilitySystemBlueprintLibrary:GetEffectContext'
            local api={GetAddress=value(101),EffectContextGetEffectCauser=function() return causer end,
                EffectContextGetOriginalInstigatorActor=function() return instigator end,
                EffectContextGetSourceObject=value(nil), GetAllActorsFromTargetData=value({param(enemy),param(ally),param(enemy)})}
            function api.GetEffectContext(self) hooks[context_path].post(param(self),param(opaque)) end
            local damage_api={GetSetByCallerMagnitudeByTag=function() return magnitude end}
            function StaticFindObject(path)
                if path:find('Default__AbilitySystemBlueprintLibrary',1,true) then return api end
                if path:find('Default__ValAbilityFunctionLibrary',1,true) then return damage_api end
                return {GetFullName=value('Function '..path)}
            end
            local env={valid=function(x)
                    assert(type(x)~='boolean','native validity requires an object or nil')
                    return type(x)=='table'
                end, aim_boosts={[1]=20},
                report=function(msg) error(msg) end, signature=function() end, combat_effects_script=effect_script}
            local controllers={{Pawn=shooter,GetAddress=value(31),GetAITargetedActor=value(enemy)},
                               {Pawn=enemy}, {Pawn=ally}}
            local close=make_observer(env,gm,{{team=1,controller=controllers[1]},
                {team=2,controller=controllers[2]}, {team=1,controller=controllers[3]}},clock,0)
            hooks['/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'].post(nil,nil,param(shot))
            local apply=hooks['/Script/GameplayAbilities.AbilitySystemComponent:BP_ApplyGameplayEffectSpecToTarget']
            local contact=hooks['/Script/Valhalla.ValProjectile:OnHit']
            local function damage(target, amount)
                apply.pre(param(shooter.AbilitySystemComponent),param(opaque),param(target.AbilitySystemComponent))
                target.hp=target.hp-amount
                apply.post()
            end
            damage(enemy,5) -- The same pawn's effect outside the tracked projectile does not count.
            local hit=param({bBlockingHit=true,bStartPenetrating=false})
            contact.pre(param(shot),nil,param(enemy),nil,nil,hit)
            causer=actor(5,0);damage(enemy,7)
            causer=shot;damage(ally,10)
            magnitude=0;damage(enemy,8)
            magnitude=-70
            local external=hooks['/Script/Valhalla.ValAbilityFunctionLibrary:ApplyExternalEffectSpec']
            controllers[1].Pawn=nil -- Retiring or respawning pawns are absent from a live roster.
            external.pre(nil,param(opaque),param(opaque))
            enemy.hp=enemy.hp-25
            external.post()
            controllers[1].Pawn=shooter
            contact.post(param(shot),nil,param(enemy),nil,nil,hit)
            local direct=hooks['/Script/Valhalla.ValBlueprintLibrary:ApplyDirectDamage']
            local second=setmetatable({GetAddress=value(6),GetFullName=value('Shot 2')},{__index=shot})
            hooks['/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'].post(nil,nil,param(second))
            direct.pre(nil,param(second),param(enemy),param(opaque))
            enemy.hp=-1
            direct.post()
            local function dispatch(index)
                local projectile=setmetatable({GetAddress=value(10+index),GetFullName=value('Shot '..index)},
                    {__index=shot})
                projectile.HitTargets={Contains=function(_,target) return projectile.accepted==target end}
                hooks['/Script/Valhalla.ValBlueprintLibrary:FinishSpawningProjectile'].post(nil,nil,param(projectile))
                contact.pre(param(projectile),nil,param(nil),nil,nil,hit)
                contact.post(param(projectile))
                return projectile
            end
            enemy.hp=100
            local third=dispatch(3)
            third.accepted=enemy
            enemy.hp=60
            assert(next_frame);next_frame()
            local fourth,fifth=dispatch(4),dispatch(5)
            fourth.accepted,fifth.accepted=enemy,enemy
            enemy.hp=45
            assert(next_frame);next_frame()
            local aim=hooks['/Script/Valhalla.ValAIBlueprintHelperLibrary:ShouldAimHitTarget']
            env.aim_boosts = {[2]=10}
            for attempt,index in ipairs({1,3,1,3,2,3}) do
                local result=false
                aim.post(nil,{get=function() return result end,set=function(_,x) result=x end},param(controllers[index]))
                assert(result == (attempt==6))
            end
            return close()
        """)
        data = list(csv.DictReader(rows.splitlines()))
        self.assertTrue(complete)
        self.assertEqual([row['event'] for row in data],
                         ['launch', 'contact', 'damage', 'launch', 'damage', 'launch', 'damage', 'launch', 'launch'])
        self.assertEqual((data[0]['target'], data[0]['aim_angle_deg'], data[0]['range_m']), ('2', '45.00', '11.00'))
        self.assertTrue(all(row['shooter_airborne']=='1' for row in data))
        self.assertEqual(data[2]['airborne'], '0')
        self.assertEqual((data[1]['target'], data[1]['damage']), ('2', ''))
        self.assertEqual((data[2]['target'], data[2]['damage'], data[2]['source']), ('2', '25.00', 'effect_application'))
        self.assertEqual((data[4]['shot'], data[4]['damage']), ('2', '55.00'))
        self.assertEqual((data[6]['shot'], data[6]['damage'], data[6]['source']), ('3', '40.00', 'native_impact'))
        samples = {int(row['bot']): int(row['adjusted']) for row in csv.DictReader(aim.splitlines())}
        self.assertEqual(samples, {1: 0, 2: 0, 3: 1})
        self.assertEqual((plan[1], plan[2]), (20, 0))

    def test_aim_calibration_requires_confirmed_damage_and_opposite_sides(self):
        self.assertEqual([trial_assignment(i) for i in range(4)],
                         [(1, 1, 10), (1, 2, 10), (2, 1, 20), (2, 2, 20)])
        opponent_contact = dict(shot=1, event='contact')
        data = dict(combat_complete=True, candidate_team=1,
                    aim=[dict(team=1, adjusted=2), dict(team=2, adjusted=0)],
                    combat=[dict(event='launch', shooter_team=team, shot=team*100 + i)
                            for team in (1, 2) for i in range(10)] + [opponent_contact])
        self.assertEqual(assess_trial(data)['teams']['1']['damaged'], 0)
        data['combat'].append(dict(shot=102, event='damage'))
        self.assertEqual(assess_trial(data)['teams']['1']['damaged'], 1)
        self.assertEqual(assess_trial(data | {'combat_complete': False})['reason'], 'partial_combat')
        played = [
            dict(aim_pair=pair, aim_level=10, candidate_team=team, aim_evidence_version=AIM_EVIDENCE_VERSION, aim_sample={
                str(team): dict(launched=10, damaged=4),
                str(3-team): dict(launched=10, damaged=1)})
            for pair in range(1, 5) for team in (1, 2)
        ]
        self.assertEqual(calibration_report([played[:-1]])['selected'], 0)
        self.assertEqual(calibration_report([played])['selected'], 10)
        self.assertEqual(calibration_report([[dict(row,aim_evidence_version=1) for row in played]])['selected'], 0)
        for leg in played:
            if leg['candidate_team'] == 2:
                leg['aim_sample']['2']['damaged'] = 0
        self.assertEqual(calibration_report([played])['selected'], 0)

    def test_aim_calibration_removes_map_side_advantage(self):
        # Blue naturally hits 70% and Red 10%. The profile adds ten points on
        # either side, even though Red on the profile loses to Blue on native aim.
        matches = [dict(aim_pair=pair, aim_level=10, candidate_team=team,
                        aim_evidence_version=AIM_EVIDENCE_VERSION,
                        aim_sample={'1': dict(launched=10, damaged=7+(team==1)),
                                    '2': dict(launched=10, damaged=1+(team==2))})
                   for pair in range(1, 5) for team in (1, 2)]
        result = calibration_report([matches])
        self.assertEqual(result['selected'], 10)
        for gain in result['profiles'][0]['gains']:
            self.assertAlmostEqual(gain, 0.1)

    def test_held_out_aim_requires_both_legs_and_keeps_side_denominators(self):
        def game(pair, candidate, teams, reason='qualified'):
            return dict(benchmark_pair=pair, candidate_team=candidate,
                        benchmark_aim_observations=dict(reason=reason, teams={
                            str(team): dict(damaged=damaged, launched=launched)
                            for team, (damaged, launched) in enumerate(teams,1)}))

        blue, red = [(4, 10), (2, 5)], [(1, 20), (1, 10)]
        result = benchmark_aim_report([
            game(1, 1, blue), game(1, 2, red),
            game(2, 1, blue), game(2, 2, red, 'partial_combat'),
            game(3, 1, blue),
        ])
        self.assertEqual((result['qualified_pairs'], result['excluded_pairs']), (1, 1))
        self.assertEqual(result['sides'][0]['candidate'], dict(damaged=4, launched=10))
        self.assertEqual(result['sides'][0]['baseline'], dict(damaged=1, launched=20))
        self.assertAlmostEqual(result['sides'][0]['mean_gain'], .35)
        self.assertAlmostEqual(result['sides'][1]['mean_gain'], -.30)
        self.assertIsNone(result['interval95'])
