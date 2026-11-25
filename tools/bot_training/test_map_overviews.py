import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from build_map_overviews import reflected_grid
from dashboard.serve_dashboard import combat_results, flag_outcomes, live_results, map_overview, trace_results


class MapOverviewTest(unittest.TestCase):
    def test_combat_response_keeps_native_classes_and_labels_observed_weapons(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            run = 'run20261120123456deadbeef'
            path = root/'DashboardRuns'/run/'progress.json'
            path.parent.mkdir(parents=True)
            rows = [{'event': 'launch', 'projectile': 'BP_Projectile_Topaz_LightSpinfusor_C'},
                    {'event': 'damage', 'projectile': 'OtherActor_C'}]
            payload = json.dumps(dict(matches=[dict(combat=rows, combat_complete=True)]))
            path.write_text(payload, encoding='utf-8')
            events = combat_results(root,run,1)['events']
            self.assertEqual(events[0], rows[0] | dict(weapon='Light Spinfusor', weapon_source='projectile_class'))
            self.assertEqual(events[1], rows[1])
            self.assertEqual(path.read_text(encoding='utf-8'), payload)

    def test_reflected_terrain_keeps_the_central_map_and_seams_aligned(self):
        grid = np.arange(9).reshape((3, 3))
        result = reflected_grid(grid, 5)
        np.testing.assert_array_equal(result[4:7, 4:7], grid)
        np.testing.assert_array_equal(result[4:7, 2:5], np.fliplr(grid))
        np.testing.assert_array_equal(reflected_grid(grid, 1), grid)
        self.assertEqual(result.shape, (11, 11))

    def test_map_endpoint_requires_a_matching_identity_and_stays_inside_the_map_folder(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'MapOverviews').mkdir()
            path = root/'MapOverviews/Damnation2026.json'
            path.write_text(json.dumps(dict(map_id='Damnation2026', image_url=None)))
            self.assertIsNone(map_overview(root, 'Damnation2026')['image_url'])
            with self.assertRaises(FileNotFoundError):
                map_overview(root, '../private')
            path.write_text('{"map_id":"Rollercoaster2026"}')
            with self.assertRaises(ValueError):
                map_overview(root, 'Damnation2026')
            path.write_text('[]')
            with self.assertRaises(ValueError):
                map_overview(root, 'Damnation2026')
            path.write_text('{"map_id":"Damnation2026","image_url":"https://example.com/image"}')
            with self.assertRaises(ValueError):
                map_overview(root, 'Damnation2026')

    def test_trace_uses_the_session_map_for_older_results(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            session = root/'Sessions/training-20261119-020000-abcdef12'
            session.mkdir(parents=True)
            trace = session/'lane-1-trace-1.csv'
            trace.write_text('seconds,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,energy,phase,ski,jet,carrying\n'
                             '0,100,200,300,0,0,100,moving,0,0,0\n')
            (session/'commit.roster').write_text('T3ROSTER1\nlease\nRollercoaster2026\n')
            identifier = 'run20261119020000abcdef12'
            run = root/'DashboardRuns'/identifier
            run.mkdir(parents=True)
            (run/'request.json').write_text('{"mode":"screen","bots":1}')
            (run/'progress.json').write_text(json.dumps(dict(waves=[dict(bots=1,
                results=[dict(lane=1, trace=str(trace))])], map='HighOctane2026')))
            result = trace_results(root, identifier, 1)
            self.assertEqual(result['map_id'], 'Rollercoaster2026')
            self.assertEqual(result['samples'][0]['world_y'], 2)

    def test_warm_team_trace_keeps_route_playback_and_path_boundary(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            session = root/'Sessions/training-20261119-020000-abcdef12'
            session.mkdir(parents=True)
            trace = session/'wave-2-team-bot-1-trace.csv'
            trace.write_text('seconds,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,energy,phase,ski,jet,carrying\n'
                             '0,100,200,300,0,0,100,flag_pickup,1,0,1\n')
            identifier = 'run20261119020000abcdef12'
            run = root/'DashboardRuns'/identifier
            run.mkdir(parents=True)
            (run/'request.json').write_text('{"mode":"scrimmage"}')
            (run/'progress.json').write_text(json.dumps(dict(matches=[dict(bots=[dict(bot=1,trace=str(trace))])],
                                                              map='Stonehenge2026')))
            result = trace_results(root, identifier, 1, 1)
            self.assertEqual(result['map_id'], 'Stonehenge2026')
            self.assertEqual(result['events'][0]['label'], 'Flag pickup')
            trace.rename(session/'wave-6-team-bot-1-trace.csv')
            with self.assertRaises(FileNotFoundError):
                trace_results(root, identifier, 1, 1)

    def test_team_throughput_excludes_untimed_history_and_counts_failed_reset_time(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            identifier = 'run20261119020000abcdef12'
            run = root/'DashboardRuns'/identifier
            run.mkdir(parents=True)
            row = dict(blue=0, red=0, seconds=30, policy='Role roster', blue_policy='Blue',
                       red_policy='Red', margin=0, bots=[])
            (run/'progress.json').write_text(json.dumps(dict(matches=[row,
                dict(row, wall_seconds=10, session_wave=2, verified_reuse=True)], reset_fallbacks=[dict(wall_seconds=4)])))
            request = dict(id=identifier, mode='scrimmage', matches=2, label='Test', status='Complete')
            phase = live_results(root, [request])['phases'][0]
            self.assertEqual(phase['timed_matches'], 1)
            self.assertEqual(phase['wall_seconds'], 14)
            self.assertEqual(phase['reused_waves'], 1)

    def test_flag_outcomes_use_side_opportunities_and_record_coverage(self):
        events = [dict(team=team, event=event) for team, event, count in (
            (1, 'flag_pickup', 2), (1, 'cap', 1), (1, 'flag_dropped', 2),
            (1, 'flag_returned', 1), (1, 'carrier_down', 1),
            (2, 'flag_pickup', 3), (2, 'carrier_down', 2), (2, 'flag_dropped', 1),
            (2, 'flag_returned', 1)) for _ in range(count)]
        match = dict(blue=1, red=0, bots=[dict(team=1), dict(team=2)], events=events, flag_returns_observed=True)
        legacy = dict(blue=5, red=4, bots=match['bots'])
        partial = dict(blue=1, red=0, bots=[dict(team=1)], events=[], flag_returns_observed=False)
        archived_capture = dict(blue=2, red=0, bots=[
            dict(team=1, pickups=4, captures=2), dict(team=1, pickups=2, captures=0)])
        totals = flag_outcomes([match, legacy, partial, archived_capture])
        self.assertEqual(totals[1]['captures'], dict(successes=3, opportunities=8, games=2))
        self.assertEqual(totals[1]['carrier_downs'], dict(successes=2, opportunities=3, games=1))
        self.assertEqual(totals[2]['carrier_downs'], dict(successes=1, opportunities=2, games=1))
        self.assertEqual(totals[1]['returns'], dict(successes=1, opportunities=2, games=1))
        self.assertEqual(totals[2]['returns'], dict(successes=1, opportunities=1, games=1))


if __name__ == '__main__':
    unittest.main()
