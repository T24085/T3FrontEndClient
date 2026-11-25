import csv
import json
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
import unittest

from defense_learning import (BASELINE, DEFENSE_ROLES, EVIDENCE_VERSION, HEAVY, LIGHT, MEDIUM,
                              TACTICS, DefenseLearning, lua_tactics, match_evidence)
from learning_history import MOVEMENT


class DefenseLearningTest(unittest.TestCase):
    def test_role_coverage_uses_flag_pressure_and_the_actual_carrier(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            bots = []
            # The closer enemy is a decoy. The actual carrier is near Light Defense.
            for index, (team, x, home, enemy, carrying) in enumerate([
                (1, 500, 500, 9500, 0), (1, 7000, 7000, 3000, 0), (1, 2500, 2500, 7500, 0),
                (2, 1000, 9000, 1000, 0), (2, 7500, 2500, 7500, 1),
            ], 1):
                trace = path/f'{index}.csv'
                with trace.open('w', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(('seconds', 'x_cm', 'y_cm', 'z_cm', 'health', 'home_flag_cm',
                                     'enemy_flag_cm', 'carrying', 'phase'))
                    for frame in range(12):
                        writer.writerow((frame / 4, x, 0, 0, 1000, home, enemy, carrying, 'InProgress'))
                bots.append(dict(bot=index, team=team, trace=str(trace), pickups=carrying))
            match = dict(blue=0, red=0, bots=bots)
            assignments = {index: (role, BASELINE) for index, role in enumerate(DEFENSE_ROLES, 1)}
            evidence = {row['role']: row for row in match_evidence(match, assignments)}
            self.assertEqual([evidence[role]['positioning'] for role in DEFENSE_ROLES], [1, 1, 0])
            self.assertAlmostEqual(evidence[LIGHT]['reward'], .9)
            self.assertLess(match_evidence(dict(match, red=1), assignments)[1]['reward'],
                            evidence[LIGHT]['reward'])
            self.assertEqual(match_evidence(dict(match, bots=bots[:3]), assignments), [])

    def test_reopens_matches_and_imports_compatible_drills_and_other_modes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)/'DashboardRuns'
            output = root/'run20261115000001aaaaaaaa'
            drill = dict(seconds=60, pickup=1, pickup_seconds=30, capture=0, defense_profile=4,
                         defense=dict(hof_alive_seconds=60, ld_alive_seconds=60,
                                      hof_near_flag_seconds=40, ld_near_carrier_seconds=15))
            other = dict(defense_evidence_version=EVIDENCE_VERSION,
                         defense_evidence=[dict(role=MEDIUM, profile='forward-screen', reward=.71)])
            own = dict(defense_evidence_version=EVIDENCE_VERSION,
                       defense_evidence=[dict(role=MEDIUM, profile='close-support', reward=.91)])

            def write(index, mode, map_id, checkpoint):
                folder = root/f'run2026111500000{index}aaaaaaaa'
                folder.mkdir(parents=True)
                (folder/'request.json').write_text(json.dumps(dict(mode=mode, map=map_id)))
                (folder/'progress.json').write_text(json.dumps(checkpoint))

            write(2, 'defended', 'HighOctane2026', dict(configuration=dict(movement=MOVEMENT), attempts=[drill]))
            write(3, 'offdef', 'HighOctane2026', dict(scenario='offense-defense-v1', matches=[other]))
            write(4, 'offdef', 'Stonehenge2026', dict(scenario='offense-defense-v1', matches=[other]))
            learning = DefenseLearning(output, 'HighOctane2026', [own])
            self.assertEqual(learning.history[MEDIUM]['forward-screen'], [.71])
            self.assertEqual(learning.history[MEDIUM]['close-support'], [.91])
            self.assertEqual(len(learning.history[HEAVY]['handoff-2500']), 1)
            self.assertEqual(len(learning.history[LIGHT]['pursuit-4']), 1)
            self.assertEqual(len(learning.sources), 3)

            for role, profiles in TACTICS.items():
                for profile in profiles:
                    reward = 1 if profile == BASELINE else 0
                    learning.record([dict(role=role, profile=profile, reward=reward)] * 100)
            roster = tuple((team, role) for team in (1, 2) for role in DEFENSE_ROLES)
            assigned = learning.assign(roster, Random(11), 0)
            self.assertEqual([assigned[slot][1] for slot in (1, 2, 3)], [BASELINE] * 3)
            self.assertTrue(all(assigned[slot][1] != BASELINE for slot in (4, 5, 6)))
            self.assertIn('[1]={handoff=1600}', lua_tactics(assigned))
