import sys
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from direct_client import DirectGame


class PublicRoundReconnectTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'lib').mkdir()
        (root / 'source').mkdir()
        (root / 'lib/owned_native_session.py').write_text('')
        (root / 'package-manifest.json').write_text(json.dumps({'startup_contract': 'verified-child-map-v1'}))
        self.current = ('public-server', 1)
        self.map = 'HighOctane2026'
        self.calls = []
        self.launched = {}
        self.closing = threading.Event()
        self.cleanup_allowed = threading.Event()
        self.successor_started = threading.Event()
        lobby = SimpleNamespace(test_source=None, public_map=self.target, public_target=self.target,
                                public_join=lambda name: self.calls.append(('join', name)),
                                public_leave=lambda: self.calls.append(('leave', None)))
        self.game = DirectGame(lobby, root, root / 'source', root / 'workspace', root / 'control',
                               catalog_loader=lambda _: {'HighOctane2026': 'a'*64, 'Stonehenge2026': 'a'*64})
        self.game.owner.run_owned_job = self.run_owned_job
        self.addCleanup(self.finish)

    def finish(self):
        self.cleanup_allowed.set()
        self.game.stop()
        self.game.wait(5)

    def target(self):
        return {'map': self.map, 'contentHash': 'a'*64, 'endpoint': '127.0.0.1:18501',
                'publicRound': self.current, 'flagIndicators': True}

    def run_owned_job(self, argv, cwd, env, artifacts, *, budget, cancellation_path):
        self.launched[self.game.public_round] = argv
        self.calls.append(('process', self.game.public_round))
        if self.game.public_round[1] == 2:
            self.successor_started.set()
        deadline = time.monotonic() + 5
        while not cancellation_path.is_file() and time.monotonic() < deadline:
            time.sleep(.01)
        self.closing.set()
        if not self.cleanup_allowed.wait(5):
            raise RuntimeError('Timed out waiting for test cleanup.')
        self.calls.append(('cleaned', self.game.public_round))
        return {'status': 'cancelled_by_owner_request', 'job_active_processes_after_cleanup': 0}

    def begin_rotation(self):
        self.assertEqual(self.game.start_public('Player'), 'starting')
        self.current = ('public-server', 2)
        self.map = 'Stonehenge2026'
        results = []
        thread = threading.Thread(target=lambda: results.append(self.game.continue_public(self.current)))
        thread.start()
        self.addCleanup(thread.join, 6)
        self.assertTrue(self.closing.wait(5))
        return thread, results

    def test_successor_waits_for_cleanup_and_keeps_seat(self):
        thread, results = self.begin_rotation()
        self.assertEqual(self.calls, [('join', 'Player'), ('process', ('public-server', 1))])
        self.cleanup_allowed.set()
        thread.join(5)
        self.assertEqual(results, ['starting'])
        self.assertEqual(self.game.public_round, self.current)
        self.assertTrue(self.successor_started.wait(5))
        argv = self.launched[self.current]
        self.assertEqual(argv[argv.index('--expected-map') + 1], 'Stonehenge2026')
        self.assertIn('--show-flag-indicators', argv)
        self.assertEqual(self.calls[:4], [('join', 'Player'), ('process', ('public-server', 1)),
                                          ('cleaned', ('public-server', 1)), ('join', 'Player')])
        self.assertNotIn(('leave', None), self.calls)

    def test_leave_while_old_round_closes_cancels_successor(self):
        thread, results = self.begin_rotation()
        self.game.stop()
        self.cleanup_allowed.set()
        thread.join(5)
        self.assertEqual(results, ['stopped'])
        self.assertEqual(self.calls[-2:], [('cleaned', ('public-server', 1)), ('leave', None)])
        self.assertEqual(self.calls.count(('join', 'Player')), 1)
