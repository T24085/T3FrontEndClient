import sys
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from direct_client import DirectClient, DirectGame, PublicCTFPanel
from community_transport import CommunityError
from steam_identity import SteamIdentityError


class PublicNameTest(unittest.TestCase):
    def test_public_join_uses_the_selected_name_or_reports_why_it_is_unavailable(self):
        panel = PublicCTFPanel.__new__(PublicCTFPanel)
        calls, status = [], []
        panel.status = SimpleNamespace(set=status.append)
        panel.team_buttons = {'auto': SimpleNamespace(cget=lambda _: 'normal'),
                              'blue': SimpleNamespace(cget=lambda _: 'normal')}
        panel.tooltip = None
        panel.desktop = SimpleNamespace(
            game=SimpleNamespace(start_public=lambda name, *, team: calls.append((name, team))),
            player_name_for_action=lambda: 'Warrior Name')
        panel.submit = lambda _action, work: work()
        panel.start('blue')
        self.assertEqual(calls, [('Warrior Name', 'blue')])

        def unavailable():
            raise SteamIdentityError('Set a Warrior Name in Settings.')

        panel.desktop.player_name_for_action = unavailable
        panel.start()
        self.assertEqual(calls, [('Warrior Name', 'blue')])
        self.assertEqual(status[-1], 'Set a Warrior Name in Settings.')


    def test_roster_counts_balance_reason_and_rejoin_render_in_tk(self):
        root = tk.Tk()
        root.geometry('660x480+0+0')
        root.attributes('-alpha', 0)
        self.addCleanup(root.destroy)
        from desktop_launcher import Desktop
        tabs = []
        desktop = SimpleNamespace(root=root, sidebar=tk.Frame(root), entry_panel=tk.Frame(root),
                                  closing=True, show_panel=tabs.append)
        desktop.label = lambda *args, **kwargs: Desktop.label(desktop, *args, **kwargs)
        desktop.button = lambda *args, **kwargs: Desktop.button(desktop, *args, **kwargs)
        panel = PublicCTFPanel(tk, desktop, SimpleNamespace(public_only=False))
        self.assertIs(panel.nav.master, desktop.entry_panel)
        panel.nav.invoke()
        self.assertEqual(tabs, ['public'])
        panel.panel.pack(fill='both', expand=True)
        state = {'teams': {'blue': ['Alice'], 'red': ['Bob', 'Carol']},
                 'joinChoices': {'auto': None, 'blue': None, 'red': 'Joining Team B would unbalance the teams.'}}
        panel.render_teams(state, True)
        root.update()
        self.assertEqual(panel.team_lists['red'][2].get(0, 'end'), ('Bob', 'Carol'))
        self.assertEqual(panel.team_lists['blue'][1].cget('text'), 'Team A (1)')
        button = panel.team_buttons['red']
        self.assertEqual((button.cget('text'), button.cget('state')), ('Join B (2)', 'disabled'))
        self.assertTrue(all(widget.winfo_ismapped() for widget in panel.team_buttons.values()))
        panel.show_team_reason(button, 'red')
        self.assertIn('unbalance', panel.tooltip.winfo_children()[0].cget('text'))
        panel.hide_team_reason()
        panel.render_teams(dict(state, rejoin=True, joinChoices={
            'auto': None, 'blue': 'Rejoin your previous team.', 'red': 'Rejoin your previous team.'
        }), True)
        self.assertEqual(panel.team_buttons['auto'].cget('text'), 'Rejoin')
        self.assertEqual(panel.team_buttons['blue'].cget('state'), 'disabled')
        panel.render_teams(dict(state, switchChoices={'blue': 'You are already on this team.', 'red': None}),
                           False, can_switch=True, switching_controls=True)
        self.assertEqual(panel.team_buttons['red'].cget('text'), 'Switch to B (2)')
        self.assertEqual(panel.team_buttons['red'].cget('state'), 'normal')
        self.assertEqual(panel.team_buttons['auto'].cget('state'), 'disabled')
        preview = {'teamCounts': {'blue': 1, 'red': 2}, 'joinChoices': state['joinChoices']}
        panel.render_teams(preview, True)
        self.assertEqual(panel.team_lists['red'][2].get(0, 'end'), ())
        self.assertEqual(panel.team_lists['blue'][1].cget('text'), 'Team A (1)')
        self.assertEqual((button.cget('text'), button.cget('state')), ('Join B (2)', 'disabled'))

    def test_public_only_play_opens_public_match_view(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        from desktop_launcher import Desktop
        tabs = []
        sidebar = tk.Frame(root)
        desktop = SimpleNamespace(root=root, sidebar=sidebar, closing=True, show_panel=tabs.append)
        desktop.label = lambda *args, **kwargs: Desktop.label(desktop, *args, **kwargs)
        desktop.button = lambda *args, **kwargs: Desktop.button(desktop, *args, **kwargs)
        desktop.lobbies_nav = desktop.button(sidebar, 'PLAY', lambda: tabs.append('lobbies'))
        desktop.live_nav = desktop.button(sidebar, 'Lobby Browser', lambda: tabs.append('live'))
        desktop.lobbies_nav.pack()
        desktop.live_nav.pack()
        PublicCTFPanel(tk, desktop, SimpleNamespace(public_only=True))
        self.assertEqual(desktop.lobbies_nav.winfo_manager(), 'pack')
        self.assertEqual(desktop.live_nav.winfo_manager(), '')
        desktop.lobbies_nav.invoke()
        self.assertEqual(tabs, ['public'])

    def test_explicit_team_uses_the_new_request_and_auto_uses_the_legacy_shape(self):
        lobby = SimpleNamespace(_public=lambda action, **request: (action, request))
        self.assertEqual(DirectClient.public_join(lobby, 'Player'), ('join', {'name': 'Player'}))
        self.assertEqual(DirectClient.public_join(lobby, 'Player', team='red'),
                         ('join', {'name': 'Player', 'team': 'red'}))


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
        lobby = SimpleNamespace(test_source=None, public_map=self.target, public_target=lambda **_: self.target(),
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

    def test_join_b_starts_a_sleeping_server_before_waiting_for_the_target(self):
        lobby = self.game.lobby
        lobby.public_map = lambda: dict(self.target(), phase='idle')
        lobby.public_join = lambda name, *, team: self.calls.append(('join', name, team))
        self.assertEqual(self.game.start_public('Player', team='red'), 'starting')
        self.assertEqual(self.calls[0], ('join', 'Player', 'red'))
        self.assertEqual(sum(item[0] == 'join' for item in self.calls), 1)

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

    def test_team_switch_rejoins_same_round_only_after_own_job_has_closed(self):
        self.assertEqual(self.game.start_public('Player'), 'starting')
        self.game.status = 'playing'
        self.game.lobby.public_switch = lambda round_id, team: (
            self.calls.append(('switch', round_id, team)) or {'switchPending':True})
        self.game.lobby.public_target = lambda **_options: (
            self.calls.append(('target', self.current)) or self.target())
        results = []
        thread = threading.Thread(target=lambda: results.append(self.game.switch_public_team(1, 'red')))
        thread.start()
        self.addCleanup(thread.join, 6)
        self.assertTrue(self.closing.wait(5))
        self.assertNotIn(('target', self.current), self.calls)
        self.cleanup_allowed.set()
        thread.join(5)
        self.assertEqual(results, ['starting'])
        self.assertEqual(self.game.public_round, self.current)
        self.assertIn(('switch', 1, 'red'), self.calls)
        self.assertLess(self.calls.index(('cleaned', self.current)), self.calls.index(('target', self.current)))
        self.assertEqual(self.calls.count(('join', 'Player')), 1)
        self.assertNotIn(('leave', None), self.calls)

    def test_denied_switch_keeps_the_current_native_game_open(self):
        self.assertEqual(self.game.start_public('Player'), 'starting')
        self.game.status = 'playing'

        def reject(round_id, team):
            raise CommunityError('That switch would unbalance the teams.')

        self.game.lobby.public_switch = reject
        with self.assertRaisesRegex(CommunityError, 'unbalance'):
            self.game.switch_public_team(1, 'red')
        self.assertEqual(self.game.status, 'playing')
        self.assertFalse((self.game.current_artifacts / 'stop.json').exists())

    def test_native_leave_request_is_written_only_to_the_current_run(self):
        self.game.run = self.game.workspace / 'client-123456789abc'
        self.game.run.mkdir(parents=True)
        self.assertTrue(self.game._request_team_departure())
        self.assertEqual((self.game.run / 'public-team-switch.txt').read_bytes(), b'leave\n')
        self.assertFalse(self.game._request_team_departure())
        self.game.run = self.game.workspace.parent / 'client-123456789abc'
        self.assertFalse(self.game._request_team_departure())

    def test_leave_while_old_round_closes_cancels_successor(self):
        thread, results = self.begin_rotation()
        self.game.stop()
        self.cleanup_allowed.set()
        thread.join(5)
        self.assertEqual(results, ['stopped'])
        self.assertEqual(self.calls[-2:], [('cleaned', ('public-server', 1)), ('leave', None)])
        self.assertEqual(self.calls.count(('join', 'Player')), 1)
