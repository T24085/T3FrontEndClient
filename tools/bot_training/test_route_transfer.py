from pathlib import Path
import json
from random import Random
from tempfile import TemporaryDirectory
import unittest

from lupa.lua54 import LuaRuntime

from paired_flag_screen import ScreenTrainer, adaptive_wave, balanced_screening_teams, screening_score, stand_speed_penalty
from route_transfer import (candidate_keys, exploratory_routes, flank_assignments, flank_routes, guided_assignments,
                            guided_evidence, ranked_routes, route_evidence)
from train import METRICS, fixed_training_teams


class RouteTransferTest(unittest.TestCase):
    def test_screening_covers_both_sides_without_overcounting_odd_rosters(self):
        self.assertEqual(balanced_screening_teams(4, []), (1, 2, 1, 2))
        prior = [{'results': [{'team': 1}, {'team': 1}, {'team': 2}]}]
        self.assertEqual(balanced_screening_teams(3, prior), (2, 1, 2))
        self.assertEqual(balanced_screening_teams(1, prior), (2,))

    def test_fixed_training_roster_uses_actual_team_capacity(self):
        template = """return function(gm,env,roster)
  local totals,teams={0,0},{}
  for _,team in pairs(roster) do totals[team]=totals[team]+1 end
  for i=1,env.bots do
   local team=totals[1]<=totals[2] and 1 or 2
   totals[team]=totals[team]+1
   assert(totals[team]<=12,'match_rules_bot_slots_exhausted')
   teams[i]=team
  end
  if env.public_fill then teams={1,2} end
  return #teams
end"""
        lua = LuaRuntime()
        warm_roster = lua.table(warm=2)
        for teams, capacity in [([1]*24, 24), ([1]*12+[2]*12, 12)]:
            with self.subTest(capacity=capacity):
                populate = lua.execute(fixed_training_teams(template, teams))
                match = lua.table(bots=24)
                self.assertEqual(populate(lua.table(MembersPerTeamOverride=capacity), match, warm_roster), 24)
                valid, error = lua.eval('pcall')(populate, lua.table(MembersPerTeamOverride=capacity-1),
                                                 match, warm_roster)
                self.assertFalse(valid)
                self.assertIn('match_rules_bot_slots_exhausted', error)

    def test_screening_reads_approach_speeds_from_native_contact(self):
        plan = dict(spawn=1, offset_cm=0, approach_route='left',
                    policy=dict(pulse=.25, period=1.8, ski=1, turn=0, flank=-1),
                    pass_runup_cm=9500, guidance=4)
        for contact, expected in [('1,80,0,0,1,95,100', (95, 100)),
                                  ('1,80,0,0,1', (None, None)), ('0', (None, None))]:
            with self.subTest(contact=contact), TemporaryDirectory() as directory:
                out = Path(directory)
                (out/'lane-1-contact-1.csv').write_text(contact, encoding='utf-8')
                (out/'lane-1-pass-1.csv').write_text('0,0,0,0,0', encoding='utf-8')
                result = ','.join(str(100 if field == 'start_energy' else int(field == 'id')) for field in METRICS)
                (out/'lane-1-result-1.csv').write_text(result+'\n', encoding='utf-8')
                trainer = ScreenTrainer([plan])
                trainer.wait = lambda _, process, ready, timeout: ready('BOT_SCREEN_READY|1|3')
                trainer.run(out, None)
                row, = trainer.results
                self.assertEqual((row.get('approach_entry_kmh'), row.get('approach_peak_kmh')), expected)
                self.assertEqual(row['contact'], contact != '0')

    def test_screened_routes_and_live_pickups_share_a_map_specific_history(self):
        candidate = dict(approach_route='left', pass_runup_cm=9500, guidance=4,
                         policy=dict(pulse=.25, period=1.8, ski=1, turn=0, flank=-1))
        guide = dict(policy=candidate['policy'], runup_cm=9500, guidance=4,
                     outcome='grab', pickup_kmh=85, homeward_kmh=80, skiing=True,
                     approach_entry_kmh=90, approach_peak_kmh=100)
        screened = dict(settings=[candidate], results=[dict(route='left', contact=True, contact_kmh=75)])
        with TemporaryDirectory() as directory:
            root = Path(directory)/'DashboardRuns'
            def write(index, mode, map_id, data):
                output = root / f'run2026111500000{index}aaaaaaaa'
                output.mkdir(parents=True)
                (output/'request.json').write_text(json.dumps(dict(mode=mode,map=map_id)),encoding='utf-8')
                (output/'progress.json').write_text(json.dumps(data),encoding='utf-8')
            write(1,'screen','HighOctane2026',dict(waves=[screened]))
            write(2,'offdef','HighOctane2026',dict(matches=[dict(guided_routes=[guide, dict(guide,outcome='censored')])]))
            write(3,'scrimmage','Stonehenge2026',dict(matches=[dict(guided_routes=[guide])]))
            rows = route_evidence(root/'run20261115000004aaaaaaaa','HighOctane2026',[candidate])
        self.assertEqual([(row['evidence'],row['contact_kmh']) for row in rows],[('screening',75),('live',85)])
        self.assertEqual((rows[1]['approach_entry_kmh'], rows[1]['approach_peak_kmh']), (90, 100))
        self.assertEqual(ranked_routes([candidate],rows,screening_score),[candidate])

    def test_slow_or_braking_pickups_lose_points(self):
        pickup = dict(contact=True, contact_kmh=80)
        steady = dict(pickup, approach_entry_kmh=80, approach_peak_kmh=80)
        accelerating = dict(pickup, approach_entry_kmh=65, approach_peak_kmh=79)
        speed_loss = dict(pickup, approach_entry_kmh=85, approach_peak_kmh=140)
        self.assertGreater(screening_score(steady), screening_score(speed_loss))
        self.assertGreater(screening_score(accelerating), screening_score(steady))
        self.assertGreater(screening_score(dict(pickup, contact_kmh=90)), screening_score(steady))
        self.assertEqual(screening_score(dict(steady, contact=False)), 0)
        self.assertEqual(stand_speed_penalty(140, 140, 144), 0)
        self.assertGreater(stand_speed_penalty(140, 150, 175), 0)
        self.assertLess(screening_score(dict(pickup, contact_kmh=14.2)), 1)

    def test_screening_and_scrimmage_still_test_new_routes_with_existing_history(self):
        tested = {'approach_route': 'tested'}
        probes = list(exploratory_routes())
        candidates = [tested, *probes]
        history = [dict(route='tested', evidence='live', contact=True, contact_kmh=160)] * 500
        starts = [{'spawn': 1, 'offset_cm': offset} for offset in range(10)]
        wave = adaptive_wave(starts, candidates, history, 1)
        self.assertEqual(sum(bool(row.get('exploratory')) for row in wave), 2)
        roster = ((1, 'Capper'), (1, 'Capper'), (2, 'Capper'), (2, 'Capper'))
        first = guided_assignments(roster, candidates, history, screening_score, 3, Random(10))
        second = guided_assignments(roster, candidates, history, screening_score, 7, Random(10))
        self.assertTrue(first[2]['exploratory'])
        self.assertEqual(first[4], tested)
        self.assertEqual(second[2], tested)
        self.assertTrue(second[4]['exploratory'])

    def test_flanks_have_distinct_entry_angles_and_transfer_only_to_matching_layout(self):
        lua = LuaRuntime()
        geometry = lua.execute(Path(__file__).with_name('route_geometry.lua').read_text())
        flag = lua.table(X=0, Y=0, Z=0)
        stock = geometry.waypoints(flag, 1, 0, 1, 9500)
        wide = geometry.waypoints(flag, 1, 0, 1, 9500, 'wide_flank')
        back = geometry.waypoints(flag, 1, 0, 1, 16000, 'back_cut')
        self.assertGreater(abs(wide[1].Y), abs(stock[1].Y))
        self.assertLess(back[2].X, -12500)
        self.assertEqual(geometry.pass_axis(flag, stock, 1, 0, None), (1, 0))
        self.assertLess(geometry.pass_axis(flag, wide, 1, 0, 'wide_flank')[1], -.75)
        mirror = geometry.waypoints(flag, 1, 0, -1, 9500, 'wide_flank')
        self.assertGreater(geometry.pass_axis(flag, mirror, 1, 0, 'wide_flank')[1], .75)
        routes = list(flank_routes())
        chosen = flank_assignments(((1, 'Capper'), (1, 'Capper'), (2, 'Light defense')),
                                   routes, [], screening_score, Random(1))
        self.assertEqual(set(chosen), {1, 2})
        self.assertNotEqual(chosen[1]['policy']['flank'], chosen[2]['policy']['flank'])
        plan = chosen[1]
        row = dict(policy=plan['policy'], runup_cm=plan['pass_runup_cm'], guidance=plan['guidance'],
                   outcome='miss', pickup_kmh=0, homeward_kmh=0, skiing=False)
        keys = candidate_keys(routes)
        self.assertEqual(list(guided_evidence([dict(guided_routes=[row])], 'run', keys)), [])
        row.update(layout=plan['layout'], pass_gap_m=5)
        actual, = guided_evidence([dict(guided_routes=[row])], 'run', keys)
        self.assertEqual((actual['route'], actual['pass_gap_m']), (plan['approach_route'], 5))

    def test_live_misses_reduce_a_screened_routes_preference(self):
        candidates = [{'approach_route': name} for name in ('left', 'right')]
        rows = [dict(route=name, evidence='screening', contact=True, contact_kmh=speed)
                for name, speed in (('left', 85), ('right', 70)) for _ in range(10)]
        self.assertEqual(ranked_routes(candidates,rows,screening_score)[0]['approach_route'],'left')
        rows.extend(dict(route='left', evidence='live', contact=False) for _ in range(10))
        self.assertEqual(ranked_routes(candidates,rows,screening_score)[0]['approach_route'],'right')
