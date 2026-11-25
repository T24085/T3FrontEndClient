from pathlib import Path
from random import Random
import unittest

from lupa.lua54 import LuaRuntime

from offense_learning import (EVIDENCE_VERSION, HEAVY_OFFENSE, MEDIUM_OFFENSE, TACTICS,
                              OffenseLearning, match_evidence)


class OffenseLearningTest(unittest.TestCase):
    def test_stalled_navigation_steers_then_restores_native_combat(self):
        lua = LuaRuntime()
        exercise = lua.execute("""
            FName = function(name) return name end
            local jet_stops, moves = 0, 0
            StaticFindObject = function()
                return {SendGameplayEventToActor=function() jet_stops=jet_stops+1 end}
            end
            return function(script, geometry, strict)
                moves,jet_stops=0,0
                local position = {X=0,Y=0,Z=0}
                local movement = {Velocity={X=strict and 330 or 0,Y=0,Z=0},
                    IsMovingOnGround=function() return true end,
                    SetWantsToSki=function(self,on) self.ski=on end}
                local pawn = {
                    CharacterMovement=movement, AbilitySystemComponent={TryActivateAbility=function() return true end},
                    GetAddress=function() return 1 end, GetEnergy=function() return 100 end,
                    GetHealth=function() return 1000 end, K2_GetActorLocation=function() return position end,
                    AddMovementInput=function() moves=moves+1 end,
                    GetEquippedAbility=function() return {Handle=1} end
                }
                local tree = {running=true, IsRunning=function(self) return self.running end,
                    StopLogic=function(self) self.running=false end}
                local controller = {Pawn=pawn, GetStateTreeComponent=function() return tree end,
                    StopMovement=function() end, StartStateTree=function() tree.running=true end}
                local request, steer, clear, finish, assist = assert(loadfile(script))()({
                    route_geometry=geometry,valid=function(item) return item~=nil end,
                    report=function() end,signature=function() end,strict_movement=strict})
                local entry, target = {controller=controller}, {X=5000,Y=0,Z=0}
                local t=0
                if not strict then
                    assert(not request(1,entry,pawn,position,target,850,0))
                    assert(not request(1,entry,pawn,position,target,850,3))
                    t=4
                end
                assert(request(1,entry,pawn,position,target,850,t))
                steer(t)
                assert(moves==1 and movement.ski and not tree.running)
                clear(1)
                assert(jet_stops==1 and not movement.ski and tree.running)
                if strict then
                    assist(1,entry,pawn,true)
                    steer(9)
                    assert(tree.running and movement.ski and moves==1)
                    steer(9.7)
                    assist(1,entry,pawn,false)
                    assert(tree.running and not movement.ski and jet_stops==2)
                    finish()
                end
            end
        """)
        root = Path(__file__).resolve().parent
        for strict in (False, True):
            exercise((root/'role_movement.lua').as_posix(), (root/'route_geometry.lua').as_posix(), strict)

    def test_rewards_pressure_before_capper_arrival_and_observed_guard_departure(self):
        bots = [dict(bot=slot, team=team, role=role, pickups=int(slot == 1))
                for slot, team, role in [(1, 1, 'Capper'), (2, 1, MEDIUM_OFFENSE),
                                         (3, 1, HEAVY_OFFENSE), (4, 2, 'Heavy on flag')]]
        assignments = {2: (MEDIUM_OFFENSE, 'timed-support'), 3: (HEAVY_OFFENSE, 'late-clear')}

        def at(x):
            return ((x, 0, 0), 10000 - x, 10000 - x, False)

        frames = {step / 4: {1: at(7000), 2: at(8500), 3: at(3000), **({4: at(9000)} if step < 6 else {})}
                  for step in range(12)}
        result = {row['role']: row for row in match_evidence(dict(blue=1, red=0, bots=bots), assignments, frames)}
        self.assertEqual(result[MEDIUM_OFFENSE]['nearby_guard_departures'], 1)
        self.assertEqual(result[HEAVY_OFFENSE]['nearby_guard_departures'], 0)
        self.assertGreater(result[MEDIUM_OFFENSE]['reward'], result[HEAVY_OFFENSE]['reward'])
        self.assertEqual(match_evidence(dict(blue=1, red=0, bots=bots), assignments, {0: frames[0]}), [])

    def test_saved_role_rewards_influence_a_later_match(self):
        winners = {MEDIUM_OFFENSE: 'timed-support', HEAVY_OFFENSE: 'early-clear'}
        evidence = [dict(role=role, profile=profile, reward=int(profile == winners[role]))
                    for role, profiles in TACTICS.items() for profile in profiles for _ in range(25)]
        match = dict(offense_evidence_version=EVIDENCE_VERSION, offense_evidence=evidence)
        model = OffenseLearning([('earlier-4v3', [match])], [])
        roster = ((1, MEDIUM_OFFENSE), (1, HEAVY_OFFENSE), (2, MEDIUM_OFFENSE), (2, HEAVY_OFFENSE))
        actual = model.assign(roster, Random(7), 0)
        self.assertEqual(actual[1], (MEDIUM_OFFENSE, winners[MEDIUM_OFFENSE]))
        self.assertEqual(actual[2], (HEAVY_OFFENSE, winners[HEAVY_OFFENSE]))
        self.assertNotEqual(actual[3][1], actual[1][1])
        self.assertEqual(model.sources['earlier-4v3'], len(evidence))
