"""Observer ownership, exact readiness and generic preparation without native game jobs."""
import json
import hashlib
import threading
import unittest
from unittest.mock import patch

from community_transport import CommunityError
from startup_progress import runtime_phase
import test_community_game as fixtures


class SpectatorGameTest(unittest.TestCase):
    # Reuse only the fixture, not its player tests.
    def setUp(self):
        fixtures.CommunityGameTest.setUp(self)
        self.lease, self.watch = 'a' * 32, 'observer_session_123'
        self.releases, self.watch_calls = [], []
        self.target = dict(endpoint='100.80.168.96:18818', map='Stonehenge', contentHash='a' * 64,
                           matchId=self.lease, watchId=self.watch, role='spectator')
        def target(watch_id):
            self.watch_calls.append(watch_id)
            return dict(self.target)
        self.lobby.spectator_target = target
        self.lobby.release_spectator = lambda watch: self.releases.append(watch)
        self.lobby.match_target = lambda: (_ for _ in ()).throw(AssertionError('observer used player roster'))
        (self.game.package / 'package-manifest.json').write_text(json.dumps(dict(startup_contract='verified-child-map-v1', spectator_contract='native-spectator-v1')))
        self.gate, self.entered = threading.Event(), threading.Event()
        self.argv = None
        def owner(argv, *args, **kwargs):
            self.argv = argv; self.entered.set(); self.gate.wait(5)
            return dict(status='cancelled_by_owner_request', job_active_processes_after_cleanup=0)
        self.game.owner.run_owned_job = owner

    def tearDown(self):
        self.gate.set()
        if self.game.thread: self.game.thread.join(5)
        fixtures.CommunityGameTest.tearDown(self)

    def test_exact_observer_readiness_and_stop_release_only_after_owned_cleanup(self):
        self.game.start_spectating(self.watch); self.assertTrue(self.entered.wait(2))
        self.assertEqual(self.watch_calls, [self.watch, self.watch])
        self.assertEqual(self.argv[self.argv.index('--match-id') + 1], self.lease)
        self.assertIn('--watch-id=' + self.watch, self.argv)
        self.assertIn('--spectate', self.argv); self.assertIn('--expected-content-hash', self.argv)
        run = self.game.workspace / 'client-spectator'; run.mkdir()
        owner = self.game.current_artifacts / 'owner'; owner.mkdir()
        (owner / 'stdout.log').write_text('Session: ' + str(run) + '\n')
        events = run / 'events.txt'
        for line in ('REMOTE_PAWN_READY|role=client',
                     'SPECTATOR_READY|lease=' + 'b' * 32 + '|watch=' + self.watch + '|target=1',
                     'SPECTATOR_READY|lease=' + self.lease + '|watch=' + self.watch + 'wrong|target=1'):
            events.write_text(line + '\n'); self.assertEqual(self.game.snapshot()['status'], 'starting')
        events.write_text('SPECTATOR_READY|lease=' + self.lease + '|watch=' + self.watch + '|target=1\n')
        self.assertEqual(self.game.snapshot()['status'], 'playing')
        self.game.stop_spectating(); self.assertEqual(self.releases, [])
        self.gate.set(); self.assertEqual(self.game.wait(3)['status'], 'stopped')
        self.assertEqual(self.releases, [self.watch]); self.assertIsNone(self.game.watch_id)

    def test_opaque_leading_dash_watcher_is_one_unmodified_option_value(self):
        self.watch = '-bDn_flATqujZ9Mk8Lex-Q'
        self.target['watchId'] = self.watch
        self.game.start_spectating(self.watch); self.assertTrue(self.entered.wait(2))
        self.assertEqual([arg for arg in self.argv if arg.startswith('--watch-id')], ['--watch-id=' + self.watch])
        self.assertEqual(self.watch_calls, [self.watch, self.watch])
        self.game.stop_spectating(); self.gate.set(); self.game.wait(3)
        self.assertEqual(self.releases, [self.watch])

    def test_normal_observer_exit_releases_and_unknown_cleanup_retains_grant(self):
        self.game.owner.run_owned_job = lambda *args, **kwargs: dict(status='terminal', exit_code=1, job_active_processes_after_cleanup=0)
        self.game.start_spectating(self.watch); self.game.wait(3)
        self.assertEqual(self.releases, [self.watch])
        self.game.owner.run_owned_job = lambda *args, **kwargs: dict(status='terminal', exit_code=1, job_active_processes_after_cleanup=1)
        self.game.start_spectating(self.watch); self.game.wait(3)
        self.assertEqual(self.game.status, 'quarantined'); self.assertEqual(self.game.watch_id, self.watch)
        self.game.stop_spectating(); self.assertEqual(self.releases, [self.watch])

    def test_failed_release_retains_identity_and_is_retryable(self):
        self.game.owner.run_owned_job = lambda *args, **kwargs: dict(status='terminal', exit_code=1, job_active_processes_after_cleanup=0)
        with patch.object(self.lobby, 'release_spectator', side_effect=CommunityError('network unavailable')):
            self.game.start_spectating(self.watch); self.game.wait(3)
            self.assertEqual(self.game.watch_id, self.watch)
            with self.assertRaises(CommunityError): self.game.start()
        self.game.stop_spectating()
        self.assertIsNone(self.game.watch_id); self.assertEqual(self.releases, [self.watch])

    def test_map_drift_or_unsupported_package_releases_without_starting_child(self):
        calls = 0
        def drift(watch_id):
            nonlocal calls
            calls += 1
            return dict(self.target, contentHash=('a' if calls == 1 else 'b') * 64)
        self.lobby.spectator_target = drift
        with self.assertRaisesRegex(CommunityError, 'match changed'): self.game.start_spectating(self.watch)
        self.assertFalse(self.entered.is_set()); self.assertEqual(self.releases, [self.watch])
        (self.game.package / 'package-manifest.json').write_text('{}')
        with self.assertRaisesRegex(CommunityError, 'Update'): self.game.start_spectating(self.watch)
        self.assertFalse(self.entered.is_set()); self.assertEqual(self.releases, [self.watch, self.watch])

    def test_role_aware_runtime_progress_never_substitutes_player_readiness(self):
        ready = 'SPECTATOR_READY|lease=' + self.lease + '|watch=' + self.watch + '|target=1'
        self.assertIsNone(runtime_phase([ready]))
        self.assertIsNone(runtime_phase(['REMOTE_PAWN_READY|role=client'], role='spectator', match_id=self.lease, watch_id=self.watch))
        self.assertEqual(runtime_phase([ready], role='spectator', match_id=self.lease, watch_id=self.watch), 'playing')

    def test_preparation_stays_role_free_then_fresh_watcher_is_handed_to_join(self):
        (self.game.package / 'package-manifest.json').write_text(json.dumps(dict(startup_contract='prepared-client-v1', spectator_contract='native-spectator-v1')))
        calls = []
        def owner(argv, cwd, env, artifacts, **kwargs):
            calls.append(argv)
            if '--prepare-only' in argv:
                run = self.game.workspace / 'client-prepared'; run.mkdir()
                descriptor = run / 'prepared.json'; descriptor.write_text('{}')
                artifacts.mkdir(parents=True)
                (artifacts / 'stdout.log').write_text('CLIENT_PREPARED|' + json.dumps(dict(path=str(descriptor), sha256=hashlib.sha256(descriptor.read_bytes()).hexdigest())) + '\n')
                return dict(status='terminal', exit_code=0, job_active_processes_after_cleanup=0)
            return dict(status='terminal', exit_code=1, job_active_processes_after_cleanup=0)
        self.game.owner.run_owned_job = owner
        self.game.start_spectating(self.watch); self.game.wait(3)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('--endpoint', calls[0]); self.assertNotIn('--spectate', calls[0])
        self.assertIn('--prepared', calls[1]); self.assertIn('--spectate', calls[1])
        self.assertEqual(self.watch_calls, [self.watch, self.watch]); self.assertEqual(self.releases, [self.watch])


if __name__ == '__main__': unittest.main()
