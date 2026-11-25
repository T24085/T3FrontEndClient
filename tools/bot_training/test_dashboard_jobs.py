import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dashboard_jobs import DashboardJobs, run_status
from aim_learning import AIM_EVIDENCE_VERSION
from dashboard_run import team_run
from learning_history import past_runs, request_provenance
from mirrored_benchmark import paired_results
from train import publish


class TrainingQueueTest(unittest.TestCase):
    request = dict(mode='screen', map='HighOctane2026', matches=4, seconds=76, bots=14)

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'practice.json').write_text('{}\n', encoding='utf-8')
        self.claimed = []
        mocks = (
            patch.object(DashboardJobs, 'maps', return_value={'HighOctane2026': 'High Octane (2026)'}),
            patch.object(DashboardJobs, 'start_worker', autospec=True, side_effect=self.claim),
            patch('dashboard_jobs.worker_busy', side_effect=lambda _: self.running),
        )
        for mock in mocks:
            mock.start()
            self.addCleanup(mock.stop)
        self.running = False
        self.jobs = DashboardJobs(self.root, self.root/'dashboard_run.py')

    def claim(self, jobs, path, request):
        publish(jobs.active_marker, path.name+'\n')
        (path/'status.json').unlink(missing_ok=True)
        self.claimed.append(request)
        self.running = True

    def finish(self, identifier, status):
        publish(self.jobs.directory/identifier/'status.json', '{"status":"' + status + '"}\n')
        self.running = False

    def test_idle_flight_can_run_before_a_waiting_season_without_releasing_its_queue(self):
        first = self.jobs.launch(self.request)
        waiting = self.jobs.launch(self.request)
        self.finish(first, 'Paused')
        flight = self.jobs.launch(dict(mode='flight', matches=3, seconds=30, bots=10))
        self.assertEqual(self.claimed[-1]['id'], flight)
        self.assertTrue(self.claimed[-1]['leave_queue_waiting'])
        self.finish(flight, 'Complete')
        self.jobs.advance_queue()
        self.assertEqual([path.name for path in self.jobs.queued_runs()], [waiting])
        with self.assertRaisesRegex(ValueError, 'even number'):
            self.jobs.launch(dict(mode='flight', matches=3, seconds=30, bots=11))

    def test_hill_course_survives_the_queue_and_repeat(self):
        first = self.jobs.launch(self.request)
        hill = self.jobs.launch(dict(mode='flight', matches=3, seconds=30, bots=10, course='uphill'))
        self.finish(first, 'Complete')
        self.jobs.advance_queue()
        self.assertEqual(self.claimed[-1]['course'], 'uphill')
        self.assertEqual(self.claimed[-1]['label'], 'Uphill jets · 10 bots')
        self.finish(hill, 'Complete')
        self.jobs.repeat(hill)
        self.assertEqual(self.claimed[-1]['course'], 'uphill')
        with self.assertRaisesRegex(ValueError, 'flight course'):
            self.jobs.launch(dict(mode='flight', matches=3, seconds=30, bots=10, course='flat'))

    def test_clear_queue_preserves_the_starting_worker_and_saved_runs(self):
        completed = self.jobs.launch(self.request)
        self.finish(completed, 'Paused')
        active = self.jobs.launch(self.request)
        waiting = [self.jobs.launch(self.request) for _ in range(7)]
        # The worker can hold the slot before removing its old Queued status.
        publish(self.jobs.directory/active/'status.json', '{"status":"Queued","queued_at":1}')

        self.assertEqual(self.jobs.clear_queue(), 7)
        self.assertEqual(self.jobs.clear_queue(), 0)
        self.assertEqual(self.jobs.active_run(), active)
        self.assertEqual(run_status(self.jobs.directory/active)['status'], 'Queued')
        self.assertEqual(run_status(self.jobs.directory/completed)['status'], 'Paused')
        self.assertTrue(all(run_status(self.jobs.directory/run)['status'] == 'Cancelled' for run in waiting))

    def test_fifo_survives_service_restart_and_preserves_settings(self):
        first = self.jobs.launch(self.request)
        next_run = self.jobs.launch(dict(self.request, bots=24))
        last = self.jobs.launch(dict(self.request, mode='scrimmage', team_size=7))
        self.jobs.advance_queue()
        self.assertEqual(len(self.claimed), 1)
        self.assertEqual([path.name for path in self.jobs.queued_runs()], [next_run, last])
        self.finish(first, 'Complete')
        self.jobs = DashboardJobs(self.root, self.root/'dashboard_run.py')
        self.jobs.advance_queue()
        self.assertEqual(self.claimed[-1]['bots'], 24)
        self.finish(next_run, 'Complete')
        self.jobs.advance_queue()
        self.assertEqual(self.claimed[-1]['id'], last)
        self.assertEqual(self.claimed[-1]['team_size'], 7)

    def test_all_map_season_preserves_order_and_pins_its_practice_settings(self):
        catalog = self.root/'current.json'
        catalog.write_text(json.dumps(dict(revision='a'*64, map_fingerprints={'NewMap': 'b'*64})), encoding='utf-8')
        (self.root/'practice.json').write_text(json.dumps(dict(map_catalog=str(catalog))), encoding='utf-8')
        with patch.object(self.jobs, 'maps', return_value={'NewMap': 'New Map', 'OtherMap': 'Other Map'}):
            first = self.jobs.launch(dict(mode='season', matches=9, seconds=60, team_size=4, waves_per_launch=3))
        self.assertEqual(self.claimed[0]['map'], 'NewMap')
        self.assertEqual(self.claimed[0]['bots'], 8)
        second, evaluation_1, evaluation_2 = self.jobs.queued_runs()
        queued = json.loads((second/'request.json').read_bytes())
        self.assertEqual((queued['map'], queued['season'], queued['matches'], queued['waves_per_launch']), ('OtherMap', first, 9, 3))
        self.assertEqual(json.loads((second/'practice.json').read_bytes())['map_catalog'], str(catalog))
        self.assertEqual(self.claimed[0]['provenance']['map_revision'], 'map:'+'b'*64)
        self.assertEqual(queued['provenance']['map_revision'], 'catalog:'+'a'*64)
        for path, map_id in ((evaluation_1, 'NewMap'), (evaluation_2, 'OtherMap')):
            evaluation = json.loads((path/'request.json').read_bytes())
            self.assertEqual((evaluation['map'], evaluation['evaluation'], evaluation['matches'],
                              evaluation['waves_per_launch']), (map_id, True, 4, 1))
        self.finish(first, 'Complete')
        self.jobs.advance_queue()
        self.assertEqual(self.claimed[-1]['id'], second.name)

    def test_mirrored_benchmark_counts_only_complete_pairs_and_keeps_them_out_of_learning(self):
        first = self.jobs.launch(dict(mode='scrimmage', matches=4, seconds=60, evaluation=True))
        report = self.jobs.directory/first/'progress.json'
        rows = [dict(benchmark_pair=1, candidate_team=1, blue=3, red=1),
                dict(benchmark_pair=1, candidate_team=2, blue=2, red=3),
                dict(benchmark_pair=2, candidate_team=2, blue=2, red=0)]
        summary = paired_results(rows)
        self.assertEqual((summary['wins'], summary['mean_margin'], summary['pending_pairs']), (1, 3, 1))
        self.assertEqual(self.claimed[0]['waves_per_launch'], 1)
        report.write_text(json.dumps(dict(matches=rows)), encoding='utf-8')
        self.assertEqual(list(past_runs(self.jobs.directory/'run20261119000000deadbeef', 'scrimmage')), [])
        with self.assertRaisesRegex(ValueError, 'mirrored pair'):
            self.jobs.launch(dict(mode='scrimmage', matches=3, seconds=60, evaluation=True))

    def test_aim_calibration_preserves_mirrored_settings_in_its_own_history(self):
        request = dict(mode='scrimmage', matches=8, seconds=60, team_size=3, aim_calibration=True,
                       waves_per_launch=4)
        first = self.jobs.launch(request)
        saved = self.jobs.directory/first
        (saved/'progress.json').write_text(json.dumps(dict(matches=[])), encoding='utf-8')
        current = self.jobs.directory/'run20261119000000deadbeef'
        self.assertEqual(list(past_runs(current, 'scrimmage')), [])
        self.assertEqual([row[0] for row in past_runs(current, 'scrimmage', aim_calibration=True)], [first])
        self.assertEqual((self.claimed[0]['team_size'], self.claimed[0]['waves_per_launch']), (3, 4))
        repeated = self.jobs.repeat(first)
        repeated_request = json.loads((self.jobs.directory/repeated/'request.json').read_bytes())
        self.assertTrue(repeated_request['aim_calibration'])
        self.assertEqual(repeated_request['waves_per_launch'], 4)
        for change in (dict(matches=7), dict(evaluation=True), dict(mode='teams')):
            with self.assertRaises(ValueError):
                self.jobs.launch(request | change)

    def test_season_benchmark_uses_only_compatible_calibration(self):
        catalog = self.root/'catalog.json'
        catalog.write_text(json.dumps(dict(map_fingerprints={'HighOctane2026': 'a'*64})), encoding='utf-8')
        runtime = self.root/'season'
        (runtime/'lua').mkdir(parents=True)
        (runtime/'lua/network.lua').write_text('return {}', encoding='utf-8')
        config = dict(map_catalog=str(catalog), season_runtime=str(runtime), runs=str(self.root/'sessions'))
        (self.root/'practice.json').write_text(json.dumps(config), encoding='utf-8')
        calibration = self.jobs.directory/self.jobs.launch(dict(
            mode='scrimmage', matches=2, seconds=60, team_size=3, aim_calibration=True))
        pinned = json.loads((calibration/'practice.json').read_bytes())
        self.assertTrue(pinned['paired_ctf_rules'])
        self.assertEqual(self.claimed[0]['capture_limit'], 5)

        def save_leg(_, trainer):
            self.assertEqual(trainer.capture_limit, 5)
            trainer.result = dict(blue=0, red=0, bots=[], guided_routes=[])
            if hasattr(trainer, 'benchmark_pair') and any(trainer.aim_boosts.values()):
                candidate = trainer.candidate_team
                launches = [dict(event='launch', shooter_team=team, shot=team*100+index)
                            for team in (1, 2) for index in range(10)]
                damage = [dict(event='damage', shot=team*100+index, shooter=team, damage=100)
                          for team in (1, 2) for index in range(4 if team==candidate else 1)]
                trainer.result.update(combat_complete=True, combat=launches+damage,
                                      aim=[dict(team=candidate, adjusted=1), dict(team=3-candidate, adjusted=0)])
            trainer.save_match(trainer)

        with patch('dashboard_run.start', side_effect=save_leg):
            team_run(pinned, calibration, 2, 60, 2026, 3, mode='scrimmage', aim_calibration=True)
        report = json.loads((calibration/'progress.json').read_bytes())
        report['matches'] = [dict(aim_pair=pair, aim_level=10, candidate_team=team,
                                  aim_evidence_version=AIM_EVIDENCE_VERSION,
                                  aim_sample={str(side): dict(launched=10, damaged=4 if side==team else 1)
                                              for side in (1, 2)})
                             for pair in range(1, 5) for team in (1, 2)]
        publish(calibration/'progress.json', json.dumps(report))
        self.jobs.launch(dict(mode='season', matches=2, seconds=60, team_size=3))
        benchmark = next(path for path in self.jobs.queued_runs()
                         if json.loads((path/'request.json').read_bytes()).get('evaluation'))
        rules = json.loads((benchmark/'request.json').read_bytes())
        self.assertEqual(rules['provenance'], self.claimed[0]['provenance'])
        with patch('dashboard_run.start', side_effect=save_leg):
            team_run(config, benchmark, 4, 60, 2026, 3, mode='season', evaluation=True)
        benchmark_report = json.loads((benchmark/'progress.json').read_bytes())
        self.assertEqual(benchmark_report['aim_benchmark_profile'], 10)
        accuracy = benchmark_report['benchmark_aim']
        self.assertEqual(accuracy['qualified_pairs'], 2)
        self.assertEqual(accuracy['sides'][1]['candidate'], dict(damaged=8, launched=20))
        self.assertEqual(accuracy['sides'][1]['baseline'], dict(damaged=2, launched=20))
        (runtime/'lua/network.lua').write_text('return {updated=true}', encoding='utf-8')
        other = self.jobs.directory/'run20261119123500deadbeef'
        other.mkdir()
        publish(other/'request.json', json.dumps(dict(
            mode='season', evaluation=True, provenance=request_provenance(config, 'HighOctane2026', 'season'))))
        with patch('dashboard_run.start', side_effect=save_leg):
            team_run(config, other, 2, 60, 2026, 3, mode='season', evaluation=True)
        other_report = json.loads((other/'progress.json').read_bytes())
        self.assertEqual(other_report['aim_benchmark_profile'], 0)

    def test_mirrored_capper_drill_reuses_routes_after_resume(self):
        output = self.root/'mirrored'
        config = {'training_map': 'HighOctane2026', 'runs': str(self.root/'sessions')}
        legs = []

        def run_leg(cfg, trainer):
            if len(legs) == 1:
                raise InterruptedError('resume check')
            save_leg(cfg, trainer)

        def save_leg(cfg, trainer):
            legs.append((trainer.roster, list(trainer.guided.values()), trainer.labels))
            trainer.result = dict(blue=0, red=0, bots=[], guided_routes=[])
            trainer.save_match(trainer)

        with patch('dashboard_run.start', side_effect=run_leg):
            with self.assertRaisesRegex(InterruptedError, 'resume check'):
                team_run(config, output, 2, 60, 2026, attack=(1, 0), mode='solo')
        with patch('dashboard_run.start', side_effect=save_leg):
            team_run(config, output, 2, 60, 2026, attack=(1, 0), mode='solo')
        report = json.loads((output/'progress.json').read_bytes())
        self.assertEqual([leg[0] for leg in legs], [((1, 'Capper'),), ((2, 'Capper'),)])
        self.assertTrue(legs[0][1])
        self.assertEqual(legs[0][1], legs[1][1])
        self.assertEqual([row['attack_team'] for row in report['matches']], [1, 2])
        self.assertNotIn('pending_mirror', report)

    def test_defender_comparison_covers_each_setup_with_the_same_route(self):
        output = self.root/'defended'
        config = {'training_map': 'HighOctane2026', 'runs': str(self.root/'sessions')}
        plans = []

        def save_leg(_, trainer):
            plans.append(list(trainer.guided.values()))
            trainer.result = dict(blue=0, red=0, bots=[], guided_routes=[])
            trainer.save_match(trainer)

        with patch('dashboard_run.start', side_effect=save_leg):
            team_run(config, output, 6, 60, 2026, attack=(1, 2), mode='defended')
        report = json.loads((output/'progress.json').read_bytes())
        at_each_setup = {}
        for row in report['matches']:
            at_each_setup.setdefault(row['policy'], []).append(row['attack_team'])
        self.assertEqual(len(at_each_setup), 3)
        self.assertTrue(all(sorted(teams) == [1, 2] for teams in at_each_setup.values()))
        self.assertTrue(plans[0])
        self.assertTrue(all(plan == plans[0] for plan in plans))

    def test_objective_rules_revision_changes_independently_of_map(self):
        catalog = self.root/'catalog.json'
        catalog.write_text(json.dumps(dict(map_fingerprints={'NewMap': 'a'*64})), encoding='utf-8')
        (self.root/'network.lua').write_text('return {}', encoding='utf-8')
        lua = self.root/'lua'
        lua.mkdir()
        objective = lua/'objectives.lua'
        objective.write_text('return {turrets=1}', encoding='utf-8')
        config = dict(map_catalog=str(catalog), host_fixture=str(self.root), host_package=str(self.root))
        original = request_provenance(config, 'NewMap', 'scrimmage')
        objective.write_text('return {turrets=2}', encoding='utf-8')
        updated = request_provenance(config, 'NewMap', 'scrimmage')
        self.assertEqual(original['map_revision'], updated['map_revision'])
        self.assertNotEqual(original['runtime_revision'], updated['runtime_revision'])

    def test_screening_reuse_is_validated_and_preserved_when_queued(self):
        self.jobs.launch(self.request)
        identifier = self.jobs.launch(dict(self.request, waves_per_launch=3))
        import json
        request = json.loads((self.jobs.directory/identifier/'request.json').read_bytes())
        self.assertEqual(request['waves_per_launch'], 3)
        for invalid in (0, 6, True, '5'):
            with self.assertRaises(ValueError):
                self.jobs.launch(dict(self.request, waves_per_launch=invalid))

    def test_all_modes_keep_wave_count_in_queue_and_repeat(self):
        self.jobs.launch(self.request)
        for mode in ('teams', 'scrimmage', 'offdef', 'explore', 'solo', 'defended'):
            with self.subTest(mode=mode):
                identifier = self.jobs.launch(dict(mode=mode, matches=3, seconds=76, waves_per_launch=2))
                import json
                manifest = json.loads((self.jobs.directory/identifier/'request.json').read_bytes())
                self.assertEqual(manifest['waves_per_launch'], 2)
                repeated = self.jobs.repeat(identifier)
                repeated_manifest = json.loads((self.jobs.directory/repeated/'request.json').read_bytes())
                self.assertEqual(repeated_manifest['waves_per_launch'], 2)
                with self.assertRaises(ValueError):
                    self.jobs.launch(dict(mode=mode, matches=3, seconds=76, waves_per_launch=True))

    def test_pause_holds_queue_and_owner_can_remove_or_start_next(self):
        first = self.jobs.launch(self.request)
        removed = self.jobs.launch(self.request)
        next_run = self.jobs.launch(self.request)
        self.jobs.queue_action(removed, 'cancel')
        self.assertEqual(run_status(self.jobs.directory/removed)['status'], 'Cancelled')
        self.finish(first, 'Paused')
        self.jobs.advance_queue()
        self.assertEqual(len(self.claimed), 1)
        self.jobs.queue_action(next_run, 'start')
        self.assertEqual(self.claimed[-1]['id'], next_run)
