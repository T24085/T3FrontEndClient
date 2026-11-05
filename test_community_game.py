import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from community_game import CommunityGame
from community_transport import CommunityError


class FakeLobby:
    test_source = None
    def __init__(self):
        self.calls = 0
        self.endpoint = '100.80.168.96:18818'
    def match_target(self):
        self.calls += 1
        if self.endpoint is None:
            raise CommunityError('The match is not ready yet.')
        return {'endpoint':self.endpoint,'map':'Stonehenge','contentHash':'a'*64,'matchId':'fixture'}


class CommunityGameTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tribes-community-game-')
        root = Path(self.temp.name)
        package, source = root/'package', root/'source'
        (package/'lib').mkdir(parents=True)
        (package/'lib/owned_native_session.py').write_text('def run_owned_job(*args, **kwargs): return {}\n')
        source.mkdir()
        self.lobby = FakeLobby()
        self.game = CommunityGame(self.lobby, package, source, root/'workspace', root/'artifacts',
                                  catalog_loader=lambda _: {'Stonehenge':'a'*64})

    def tearDown(self):
        self.temp.cleanup()

    def test_only_fresh_lobby_endpoint_and_owned_stop(self):
        event = threading.Event()
        captured = {}
        def run(argv, cwd, env, artifacts, budget, cancellation_path):
            captured['argv'] = argv
            event.wait(5)
            return {'status':'cancelled_by_owner_request','job_active_processes_at_parent_exit':0}
        self.game.owner.run_owned_job = run
        self.assertEqual(self.game.start(), 'starting')
        self.assertEqual(self.lobby.calls, 2)
        with self.assertRaises(CommunityError):
            self.game.start()
        self.game.stop()
        event.set()
        self.assertEqual(self.game.wait(5)['status'], 'stopped')
        self.assertIn('100.80.168.96:18818', captured['argv'])
        self.assertNotIn('-server', captured['argv'])

    def test_unready_lobby_does_not_start(self):
        self.lobby.endpoint = None
        with self.assertRaises(CommunityError):
            self.game.start()
        self.assertEqual(self.game.snapshot()['status'], 'failed')

    def test_staging_failure_reports_child_reason_without_native_process(self):
        reason = 'Insufficient staging storage: need file bytes=8452589081 plus 2 GiB reserve; free=6568361984.'
        def run(argv, cwd, env, artifacts, budget, cancellation_path):
            artifacts.mkdir(parents=True)
            (artifacts/'stdout.log').write_text('CLIENT_STARTUP|phase=staging_game\nUnable to join: '+reason+'\n')
            return {'status':'terminal','exit_code':1,'job_active_processes_at_parent_exit':0}
        self.game.owner.run_owned_job = run
        self.game.start()
        result = self.game.wait(5)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], reason)

    def test_startup_reason_does_not_hide_unknown_process_cleanup(self):
        def run(argv, cwd, env, artifacts, budget, cancellation_path):
            artifacts.mkdir(parents=True)
            (artifacts/'stdout.log').write_text('Unable to join: staging failed\n')
            return {'status':'terminal','exit_code':1}
        self.game.owner.run_owned_job = run
        self.game.start()
        result = self.game.wait(5)
        self.assertEqual(result['status'], 'quarantined')
        self.assertIn('cleanup',result['error'])

    def test_mismatched_map_never_starts_game(self):
        self.game.catalog_loader=lambda _: {'Stonehenge':'b'*64}
        with self.assertRaises(CommunityError): self.game.start()
        self.assertEqual(self.game.snapshot()['status'],'failed')
        self.assertIsNone(self.game.thread)

    def test_changed_match_during_map_verification_never_starts_game(self):
        def load(_):
            self.lobby.endpoint='100.80.168.96:18819'
            return {'Stonehenge':'a'*64}
        self.game.catalog_loader=load
        with self.assertRaises(CommunityError): self.game.start()
        self.assertEqual(self.game.snapshot()['status'],'failed')
        self.assertIsNone(self.game.thread)

    def test_verification_does_not_block_snapshots_and_stop_prevents_launch(self):
        entered, release = threading.Event(), threading.Event()
        called = []
        def load(_):
            entered.set()
            release.wait(5)
            return {'Stonehenge':'a'*64}
        self.game.catalog_loader = load
        self.game.owner.run_owned_job = lambda *a, **k: called.append(True)
        thread = threading.Thread(target=self.game.start)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            snapshot_done = threading.Event()
            states = []
            def read():
                states.append(self.game.snapshot())
                snapshot_done.set()
            reader = threading.Thread(target=read)
            reader.start()
            self.assertTrue(snapshot_done.wait(1), 'verification held the UI snapshot lock')
            reader.join(1)
            self.assertEqual(states[0]['status'], 'starting')
            self.assertEqual(states[0]['progress'], 'Checking map files…')
            self.game.stop()
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(self.game.snapshot()['status'], 'stopped')
        self.assertEqual(called, [])

    def test_new_contract_delegates_authenticated_selected_map_to_owned_child(self):
        import json
        (self.game.package/'package-manifest.json').write_text(json.dumps({'startup_contract':'verified-child-map-v1'}))
        def unexpected(_): raise AssertionError('duplicate parent hash')
        self.game.catalog_loader = unexpected
        done = threading.Event()
        captured = []
        def run(argv, *a, **k):
            captured.extend(argv)
            done.set()
            return {'status':'terminal','exit_code':1,'job_active_processes_after_cleanup':0}
        self.game.owner.run_owned_job = run
        self.game.start()
        self.assertTrue(done.wait(2))
        self.game.wait(2)
        self.assertEqual(captured[captured.index('--expected-map')+1], 'Stonehenge')
        self.assertEqual(captured[captured.index('--expected-content-hash')+1], 'a'*64)

    def test_unconfirmed_cleanup_is_quarantined(self):
        self.game.owner.run_owned_job = lambda *a,**k: {'status':'terminal','exit_code':0,'job_active_processes_at_parent_exit':1}
        self.game.start()
        self.assertEqual(self.game.wait(5)['status'], 'quarantined')
        with self.assertRaises(CommunityError):
            self.game.start()

    def test_runtime_failure_after_spawn_stops_owned_client_and_reports_failure(self):
        gate=threading.Event()
        def owner(*args,**kwargs):
            if not gate.wait(5): raise RuntimeError('test timed out')
            return {'status':'cancelled_by_owner_request','job_active_processes_after_cleanup':0}
        self.game.owner.run_owned_job=owner
        self.game.start()
        try:
            run=self.game.workspace/'client-test';run.mkdir()
            owner_dir=self.game.current_artifacts/'owner';owner_dir.mkdir(exist_ok=True)
            (owner_dir/'stdout.log').write_text('Session: '+str(run)+'\n')
            events=run/'events.txt'
            events.write_text('REMOTE_PAWN_READY|role=client-extra\n')
            self.assertEqual(self.game.snapshot()['status'],'starting')
            events.write_text('REMOTE_PAWN_READY|role=client\n')
            self.assertEqual(self.game.snapshot()['status'],'playing')
            events.write_text(events.read_text()+'JETPACK_INPUT_ERROR|failure after spawn\n')
            with patch('community_game.os.replace',side_effect=OSError('busy')):
                with self.assertRaises(CommunityError): self.game.snapshot()
            self.assertEqual(self.game.status,'stopping')
            self.assertFalse(self.game.cancellation_written)
            self.assertEqual(self.game.snapshot()['status'],'stopping')
            self.assertTrue((self.game.current_artifacts/'stop.json').is_file())
        finally:
            gate.set()
        state=self.game.wait(5)
        self.assertEqual(state['status'],'failed')
        self.assertIn('runtime',state['error'])

    def test_missing_playing_evidence_does_not_report_connected(self):
        gate=threading.Event()
        def owner(*args,**kwargs):
            gate.wait(5)
            return {'status':'terminal','exit_code':1,'job_active_processes_after_cleanup':0}
        self.game.owner.run_owned_job=owner;self.game.start()
        try:
            run=self.game.workspace/'client-test';run.mkdir()
            owner_dir=self.game.current_artifacts/'owner';owner_dir.mkdir(exist_ok=True)
            (owner_dir/'stdout.log').write_text('Session: '+str(run)+'\n')
            events=run/'events.txt';events.write_text('REMOTE_PAWN_READY|role=client\n')
            self.assertEqual(self.game.snapshot()['status'],'playing')
            events.unlink()
            with self.assertRaises(CommunityError): self.game.snapshot()
        finally:
            gate.set();self.game.wait(5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
