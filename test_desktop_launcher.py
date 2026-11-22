"""Exercise desktop controls with a fake lobby and game, without network or game launch."""
import time
import gc
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from desktop_launcher import Desktop, match_phase_text, normalize_lobby_code
from community_transport import CommunityError
from community_maps import options
from steam_identity import SteamIdentityError, read_local_name, save_local_name


class FakeLobby:
    def __init__(self):
        self.room = {'code':'ABC234','map':'Stonehenge','phase':'setup','playerId':'one',
                     'players':[{'id':'one','name':'One','team':None,'leader':True},
                                {'id':'two','name':'Two','team':None,'leader':False}]}
        self.calls = []
    def capabilities(self): return {'matchStartEnabled':True,'gameClientReady':True}
    def create(self,name): self.calls.append(('create',name));return self.room
    def join(self,code,name): self.calls.append(('join',code,name));return self.room
    def action(self,operation,**data):
        self.calls.append((operation,data))
        if operation=='team':
            ident=data.get('playerId','one')
            next(p for p in self.room['players'] if p['id']==ident)['team']=data['team']
        elif operation=='map': self.room['map']=data['map']
        elif operation=='start': self.room['phase']='ready'
        elif operation=='stop': self.room['phase']='stopped'
        elif operation=='leave': return None
        return self.room


class FakeGame:
    def __init__(self): self.started=False;self.stopped=False
    def start(self, *, expected_map=None, expected_match_id=None): self.started=True;return 'starting'
    def snapshot(self): return {'status':'playing' if self.started else 'idle','error':None,'run':None}
    def stop(self): self.stopped=True


class DesktopTest(unittest.TestCase):
    def tearDown(self):
        gc.collect()  # Tcl variables retain thread affinity after root.destroy().

    def test_private_match_browser_displays_lock_and_rejoin(self):
        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        app = Desktop(root, lobby, lambda _: FakeGame())
        try:
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            app.caps.update(privateLobbyAdmission=True, gameClientReady=True)
            app.render(None)
            self.assertEqual(app.lobby_lock.winfo_manager(), 'grid')
            app.lock_lobby.set(True)
            with patch.object(app, 'enter_lobby') as enter, patch.object(lobby, 'create') as create:
                app.create()
                enter.call_args.args[0]('Player')
                create.assert_called_once_with('Player', locked=True)
            app.caps['lobbyMatchTypes'] = True
            app.lobby_match_type.set('Scrim')
            app.change_lobby_match_type(None)
            self.assertTrue(app.lock_lobby.get())
            self.assertEqual(app.lobby_lock.cget('state'), 'disabled')
            with patch.object(app, 'enter_lobby') as enter, patch.object(lobby, 'create') as create:
                app.create()
                enter.call_args.args[0]('Player')
                create.assert_called_once_with('Player', locked=True, match_type='scrim')
            match_id = 'a'*32
            locked = {'id':match_id, 'label':'Stonehenge', 'playerCount':2, 'playerCapacity':24,
                      'spectatorCount':0, 'spectatorCapacity':0, 'canSpectate':False,
                      'locked':True, 'rejoin':False, 'canJoin':False,
                      'joinReason':'Match in progress, lobby locked.', 'teamCounts':{'blue':1,'red':1}}
            app.render_live_matches([locked])
            app.live_list.selection_set(match_id)
            app.render_live_controls()
            self.assertEqual(app.live_join_button.cget('state'), 'disabled')
            self.assertEqual(app.live_join_reason.get(), 'Match in progress, lobby locked.')
            self.assertIn('Locked', app.live_list.item(match_id, 'values')[1])
            app.render_live_matches([dict(locked, rejoin=True, canJoin=True, joinReason='')])
            self.assertEqual(app.live_join_button.cget('text'), 'Rejoin')
            self.assertEqual(app.live_join_button.cget('state'), 'normal')
            self.assertEqual(str(app.live_team.cget('state')), 'disabled')
            app.render_live_matches([dict(locked, locked=False, canJoin=True, joinReason='')])
            self.assertEqual(str(app.live_team.cget('state')), 'readonly')
            app.live_team.current(2)
            with patch.object(app, 'enter_lobby') as enter, patch.object(lobby, 'join_match', create=True) as join:
                app.join_live_selected()
                enter.call_args.args[0]('Player')
                join.assert_called_once_with(match_id, 'Player', team='red')
        finally:
            root.destroy()

    def test_restart_controls_and_owned_client_handoff(self):
        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        game = FakeGame()
        app = Desktop(root, lobby, lambda _: game)
        try:
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            app.caps.update(matchRestartEnabled=True, gameClientReady=True)
            lobby.room.update(phase='ready', match={'id':'previous','status':'ready'})
            app.render(lobby.room)
            self.assertEqual(app.restart_button.cget('state'), 'normal')
            with patch('desktop_launcher.simpledialog.askstring', return_value='Dropped player'):
                with patch.object(app, 'call_action') as action:
                    app.restart_button.invoke()
            action.assert_called_once_with('restart', matchId='previous', reason='Dropped player')

            app.caps['matchRestartKeepScore'] = True
            lobby.room['match']['loading'] = {'state': 'playing'}
            with patch('desktop_launcher.messagebox.askyesnocancel', return_value=True), \
                    patch('desktop_launcher.simpledialog.askstring', return_value='Dropped player'), \
                    patch.object(app, 'call_action') as action:
                app.restart_button.invoke()
            action.assert_called_once_with('restart', matchId='previous', reason='Dropped player', mode='keep_score')

            lobby.room['restart'] = {'stage':'countdown','matchId':'previous','seconds':7,'reason':'Dropped player'}
            app.render(lobby.room)
            self.assertEqual(app.phase.get(), 'Restarting in 7s · Dropped player')
            self.assertEqual(app.game_button.cget('state'), 'disabled')
            self.assertEqual(app.restart_button.cget('state'), 'disabled')
            app.game = game
            previous = {'status':'playing','matchId':'previous','role':'player'}
            self.assertFalse(app.stop_restarted_client(previous))
            lobby.room['restart']['stage'] = 'checkpointing'
            app.render(lobby.room)
            self.assertEqual(app.phase.get(), 'Saving current score and time · Dropped player')
            self.assertEqual(app.game_button.cget('state'), 'disabled')
            self.assertEqual(app.restart_button.cget('state'), 'disabled')
            self.assertFalse(app.stop_restarted_client(previous))
            self.assertFalse(game.stopped)
            lobby.room['restart']['stage'] = 'draining'
            self.assertFalse(app.stop_restarted_client(dict(previous, role='spectator')))
            self.assertFalse(app.stop_restarted_client(dict(previous, matchId='other')))
            self.assertTrue(app.stop_restarted_client(previous))
            self.assertTrue(game.stopped)

            lobby.room['match'] = {'id':'replacement','status':'ready'}
            lobby.room['players'][0]['team'] = 'blue'
            lobby.room['restart'].update(stage='restoring', replacementMatchId='replacement')
            app.render(lobby.room)
            self.assertIn('restoring the score and clock', app.phase.get())
            self.assertEqual(app.game_button.cget('state'), 'normal')
            self.assertEqual(app.stop_button.cget('state'), 'normal')
            app.game_status = 'stopped'
            app.join_attempted_match = 'previous'
            with patch.object(app, 'join_game') as join_game:
                app.maybe_auto_join()
            join_game.assert_called_once()
            lobby.room['restart']['stage'] = 'complete'
            app.render(lobby.room)
            self.assertEqual(app.game_button.cget('state'), 'normal')
        finally:
            app.close()

    def test_lobby_code_paste_cleans_invite_text_and_only_joins_when_clicked(self):
        for value in ('  abc234  ', 'Lobby code: abc234\n', 't3://join/abc234',
                      'https://friend.test/lobby/join/abc234', 'https://friend.test/lobby?code=abc234'):
            self.assertEqual(normalize_lobby_code(value), 'ABC234')
        for value in ('no lobby code here', 'ABC123', 't3://unknown/abc234', 'ABC234 XYZ'):
            self.assertIsNone(normalize_lobby_code(value))

        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        app = Desktop(root, lobby, lambda _: FakeGame())
        try:
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            root.clipboard_clear()
            root.clipboard_append('Lobby code: abc234\n')
            app.paste_code_button.invoke()
            self.assertEqual(app.code.get(), 'ABC234')
            self.assertEqual(lobby.calls, [])
            self.assertEqual(app.code_menu.entrycget(0, 'label'), 'Paste')
            app.name.set('Pilot')
            app.join_button.invoke()
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertEqual(lobby.calls, [('join', 'ABC234', 'Pilot')])
            self.assertEqual(app.paste_code_button.cget('state'), 'disabled')
        finally:
            app.close()

    def test_lobby_notices_clear_on_room_change_and_transient_messages_expire(self):
        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        sync = Mock(session_enabled=False, notice_target=None, notice_active=False,
                    status='', progress=None, cancelled=Event())
        app = Desktop(root, lobby, lambda _: FakeGame(), map_sync=sync)
        try:
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            app.render(lobby.room)
            app.status.set('Game files changed.')
            app.preparation.set('Preparing old match.')
            app.map_status.set('Old map ready.')
            app.render(None)
            self.assertEqual((app.status.get(), app.preparation.get(), app.map_status.get()), ('', '', ''))

            app.status.set('Left lobby.')
            app.render(dict(lobby.room, code='XYZ789'))
            self.assertEqual(app.status.get(), '')

            sync.status = 'Old lobby download completed.'
            sync.notice_target = ('Stonehenge', 'a' * 64, 'b' * 64)
            app.status.set('Earlier transient message')
            with patch('desktop_launcher.NOTICE_MS', 30):
                app.status.set('Latest transient message')
                deadline = time.monotonic() + 2
                while app.status.get() and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.01)
                self.assertEqual(app.status.get(), '')
                root.update()
                self.assertEqual(app.map_status.get(), '')
        finally:
            app.close()

    def test_artwork_stays_behind_lobby_and_spectator_controls(self):
        root = tk.Tk()
        # Tk's coordinate hit-test includes other desktop windows on Windows.
        root.attributes('-topmost', True)
        lobby = FakeLobby()
        app = Desktop(root, lobby, lambda _: FakeGame())

        def check_hits(*widgets):
            root.update()
            for widget in widgets:
                x = widget.winfo_rootx() + widget.winfo_width() // 2
                y = widget.winfo_rooty() + widget.winfo_height() // 2
                self.assertIs(root.winfo_containing(x, y), widget, str(widget))

        try:
            for size in ('850x740', '1140x800'):
                root.geometry(size + '+0+0')
                app.show_panel('lobbies')
                app.render(None)
                check_hits(app.lobby_create_button, app.join_button, app.entry_map, app.code_entry)
                app.render(lobby.room)
                check_hits(app.map_combo, app.start_button, app.game_button)
                app.live_nav.invoke()
                check_hits(app.spectate_button, app.create_button)
        finally:
            app.close()

    def test_maps_browser_manages_downloads_and_lobby_changes_prefetch_only_the_selection(self):
        sync = Mock(session_enabled=True, cancelled=Event(), status='', progress=None, local_version=0)
        metadata = {'id':'Stonehenge', 'label':'Stonehenge', 'gameTag':'Community', 'bytes':1048576,
                    'contentHash':'a'*64, 'manifestHash':'b'*64}
        download = dict(metadata, state='Update available', removable=True)
        release_catalog = Event()
        def fetch_index():
            release_catalog.wait(3)
            return [metadata]
        sync.refresh_map_index.side_effect = fetch_index
        sync.local_maps.side_effect = lambda _: [dict(download)]
        sync.sync_map.side_effect = lambda *_, **_options: download.update(state='Downloaded')
        sync.remove_map.side_effect = lambda *_: download.update(state='Not downloaded', removable=False)
        root = tk.Tk(); root.withdraw()
        lobby = FakeLobby()
        lobby.capabilities = lambda: {'mapFileSync':2, 'mapSessionSync':3, 'matchStartEnabled':True,
                                      'maps':[{'id':'Stonehenge', 'label':'Stonehenge'}]}
        app = Desktop(root, lobby, lambda _: FakeGame(), map_sync=sync)

        def wait(predicate):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                root.update()
                if predicate():
                    return
                time.sleep(.01)
            self.fail('Map browser did not complete its action.')

        try:
            wait(lambda: not app.busy)
            sync.start.assert_called_once_with(2, session_version=3)
            app.show_panel('maps')
            self.assertEqual(app.maps_table.get_children(), ('Stonehenge',))
            self.assertTrue(app.map_index_busy)
            release_catalog.set()
            wait(lambda: app.map_rows.get('Stonehenge', {}).get('state') == 'Update available')
            sync.refresh_map_index.assert_called_once()
            sync.prefetch.assert_not_called()
            app.maps_table.selection_set('Stonehenge')
            root.update()
            self.assertEqual(app.map_download.cget('text'), 'Download selected')
            app.map_download.invoke()
            wait(lambda: not app.busy and app.map_rows['Stonehenge']['state'] == 'Downloaded')
            self.assertEqual(sync.sync_map.call_args.args, ('Stonehenge', 'a'*64, 'b'*64))
            self.assertEqual(sync.sync_map.call_args.kwargs['notice_target'], 'Stonehenge')
            app.map_remove.invoke()
            wait(lambda: not app.busy and app.map_rows['Stonehenge']['state'] == 'Not downloaded')
            sync.remove_map.assert_called_once_with('Stonehenge')
            joining, release = Event(), Event()

            def join():
                joining.set()
                release.wait(2)

            try:
                self.assertTrue(app.run_async(join, lambda _: None))
                self.assertTrue(joining.wait(1))
                sync.refresh_map_index.side_effect = CommunityError('Temporary network problem')
                app.show_panel('lobbies')
                app.show_panel('maps')
                self.assertEqual(app.maps_table.get_children(), ('Stonehenge',))
                wait(lambda: 'may be out of date' in app.maps_notice.get())
                self.assertTrue(app.busy)
                self.assertEqual(app.maps_table.selection(), ('Stonehenge',))
            finally:
                release.set()
                wait(lambda: not app.busy)
            original = dict(lobby.room, contentHash='a'*64, manifestHash='b'*64)
            app.render(original)
            app.render(original)
            changed = dict(original, map='Snowblind', contentHash='c'*64, manifestHash='d'*64)
            app.render(changed)
            self.assertEqual([call.args[0] for call in sync.prefetch.call_args_list], [
                ('Stonehenge', 'a'*64, 'b'*64), ('Snowblind', 'c'*64, 'd'*64)])
        finally:
            app.close()
            app.close_worker.join(2)

    def test_maps_queue_skips_installed_maps_sorts_and_cancels_individual_or_all_downloads(self):
        root = tk.Tk()
        root.withdraw()
        catalog = [
            {'id': 'First', 'label': 'First', 'bytes': 4},
            {'id': 'Second', 'label': 'Second', 'bytes': 12},
            {'id': 'Installed', 'label': 'Installed', 'bytes': 3},
        ]
        metadata = [dict(row, gameTag='Community', contentHash='a'*64, manifestHash='b'*64) for row in catalog]
        sync = Mock(session_enabled=True, cancelled=Event(), status='', notice_target=None,
                    progress=None, local_version=0)
        sync.refresh_map_index.return_value = metadata
        sync.local_maps.side_effect = lambda rows: [
            dict(row, state='Downloaded' if row['id']=='Installed' else 'Not downloaded',
                 removable=False) for row in rows]
        lobby = FakeLobby()
        lobby.capabilities = lambda: {'mapFileSync':2, 'mapSessionSync':3, 'matchStartEnabled':True}
        started, finish = Event(), Event()
        def download(identity, _content, _manifest, *, obsolete, notice_target):
            self.assertEqual(notice_target, identity)
            sync.notice_target, sync.progress = identity, (1, 4)
            started.set()
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    obsolete()
                    if finish.wait(.015):
                        return None
                raise CommunityError('Test download stalled')
            finally:
                sync.progress = None
        sync.sync_map.side_effect = download
        app = Desktop(root, lobby, lambda _: FakeGame(), map_sync=sync)

        def wait(predicate):
            deadline = time.monotonic()+3
            while not predicate() and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertTrue(predicate())

        try:
            app.show_panel('maps')
            wait(lambda: len(app.map_rows)==3 and app.map_rows['First']['state']=='Not downloaded')
            self.assertEqual(str(app.maps_table.cget('selectmode')), 'extended')
            app.select_all_maps()
            app.sort_maps('size')
            self.assertEqual(app.maps_table.get_children(), ('Installed', 'First', 'Second'))
            app.sort_maps('size')
            self.assertEqual(app.maps_table.get_children(), ('Second', 'First', 'Installed'))
            self.assertEqual(set(app.maps_table.selection()), {'First', 'Second', 'Installed'})
            app.queue_selected_maps()
            self.assertTrue(started.wait(2))
            self.assertEqual(sync.sync_map.call_args.args[0], 'Second')
            wait(lambda: '1/4 files' in app.map_queue_notice.get())

            app.maps_table.selection_set('First')
            app.cancel_selected_maps()
            self.assertEqual(list(app.map_queue), [])
            self.assertEqual(app.map_queue_cancelled, 1)
            app.show_panel('lobbies')
            app.show_panel('maps')
            self.assertEqual(app.maps_table.get_children(), ('Second', 'First', 'Installed'))
            self.assertEqual(app.maps_table.selection(), ('First',))
            app.cancel_all_maps()
            wait(lambda: app.map_active is None)
            self.assertIn('2 cancelled', app.map_queue_notice.get())
            self.assertEqual(sync.sync_map.call_count, 1)
        finally:
            finish.set()
            app.close()

    @unittest.skipUnless(sys.platform == 'win32', 'Retail profile import is a Windows Starter control.')
    def test_settings_import_button_uses_saved_profile_only_after_game_exits(self):
        root = tk.Tk()
        root.withdraw()
        app = Desktop(root, FakeLobby(), lambda _: FakeGame())
        try:
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            settings = next(widget for widget in app.sidebar.winfo_children()
                            if isinstance(widget, tk.Button) and widget.cget('text') == 'Settings')
            with patch('player_profile.import_retail_settings', return_value=('Input.ini',)) as importer:
                settings.invoke()
                panel = app.settings_window
                button = next(widget for widget in panel.winfo_children() if isinstance(widget, tk.Button))
                status = next(widget for widget in panel.winfo_children()
                              if isinstance(widget, tk.Label) and widget.cget('textvariable'))
                self.assertEqual(button.cget('text'), 'Import settings from retail')
                app.game_status = 'playing'
                button.invoke()
                importer.assert_not_called()
                self.assertIn('Close TRIBES 3', status.cget('text'))
                app.game_status = 'finished'
                button.invoke()
                importer.assert_called_once()
                self.assertIn('Retail settings imported.', status.cget('text'))
        finally:
            app.close()
            app.close_worker.join(2)

    def test_spectate_actions_fit_on_first_open(self):
        for size, scaling in (('1030x800', 1.333), ('850x740', 1.75)):
            with self.subTest(size=size, scaling=scaling):
                root = tk.Tk()
                root.attributes('-alpha', 0)
                root.tk.call('tk', 'scaling', scaling)
                app = Desktop(root, FakeLobby(), lambda _: FakeGame())
                try:
                    root.geometry(size)
                    root.update_idletasks()
                    with patch.object(app, 'refresh_live_matches'):
                        app.live_nav.invoke()
                    root.update_idletasks()

                    actions = (app.spectate_button, app.stop_watch_button, app.live_refresh_button)
                    for button in (*actions, app.live_list, app.live_roster_table):
                        self.assertTrue(button.winfo_ismapped(), str(button))
                        self.assertGreaterEqual(button.winfo_width(), 1)
                        self.assertGreater(button.winfo_height(), 1)
                    for button in actions:
                        self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
                        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                        self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                             app.live_list.winfo_rooty())
                    self.assertEqual(app.spectate_button.cget('state'), 'disabled')
                finally:
                    app.close()
                    app.close_worker.join(2)

    def test_selected_live_match_displays_and_refreshes_team_names(self):
        root = tk.Tk()
        root.withdraw()
        app = Desktop(root, FakeLobby(), lambda _: FakeGame())
        try:
            first = dict(id='a'*32, label='Stonehenge', playerCount=3, playerCapacity=24,
                         spectatorCount=0, spectatorCapacity=25, canSpectate=True,
                         roster={'blue':['Blue A','Blue B'],'red':['Red A']})
            second = dict(first, id='b'*32, roster={'blue':['Blue C'],'red':['Red B']})
            app.render_live_matches([first, second])
            app.live_list.selection_set(first['id'])
            app.select_live_match(None)
            table = app.live_roster_table
            self.assertEqual([list(table.item(row, 'values')) for row in table.get_children()],
                             [['Blue A','Red A'],['Blue B','']])
            app.render_live_matches([dict(first, roster={'blue':['Blue B'],'red':['Red D']}), second])
            self.assertEqual(app.live_list.selection(), (first['id'],))
            self.assertEqual(table.item(table.get_children()[0], 'values'), ('Blue B','Red D'))
            app.live_list.selection_set(second['id'])
            app.select_live_match(None)
            self.assertEqual(table.item(table.get_children()[0], 'values'), ('Blue C','Red B'))
            legacy = {key:value for key,value in second.items() if key!='roster'}
            app.render_live_matches([legacy])
            self.assertEqual(app.live_roster_status.get(), 'Roster unavailable')
            self.assertFalse(table.get_children())
        finally:
            app.close()
            app.close_worker.join(2)

    def test_match_rules_controls_respect_map_and_leader(self):
        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        app = Desktop(root, lobby, lambda _: FakeGame())
        try:
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertFalse(app.busy)
            self.assertFalse(app.rules_row.winfo_manager())
            app.caps['matchRulesEnabled'] = True
            lobby.room.update(map='Katabatic', blueSide='A',
                              availableMaps=options(('Katabatic', 'Rollercoaster2026')), rules={
                'flagIndicators':True, 'botCount':4, 'retailCapturePoint':False,
            })
            app.render(lobby.room)
            self.assertEqual(app.rules_row.winfo_manager(), 'pack')
            self.assertFalse(app.fall_toggle.winfo_manager())
            app.caps['fallDamageEnabled'] = True
            lobby.room['rules']['fallDamage'] = True
            app.render(lobby.room)
            self.assertEqual(app.fall_toggle.winfo_manager(), 'pack')
            self.assertEqual(app.fall_toggle.cget('state'), 'normal')
            self.assertTrue(app.fall_damage.get())
            calls = []
            original_action = app.call_action
            app.call_action = lambda op, **changes: calls.append((op, changes))
            app.fall_toggle.invoke()
            self.assertEqual(calls, [('rules', {'fallDamage': False})])
            app.call_action = original_action
            self.assertTrue(app.flag_indicators.get())
            self.assertEqual(app.bot_count.get(), '4')
            self.assertEqual(str(app.bot_spinner.cget('state')), 'readonly')
            self.assertEqual(app.capture_toggle.cget('state'), 'normal')
            self.assertFalse(app.retail_capture_point.get())
            self.assertEqual(str(app.side_combo.cget('state')), 'readonly')
            app.blue_side.set('Side B')
            with patch.object(app, 'call_action') as call:
                app.choose_side()
                call.assert_called_once_with('rules', blueSide='B')
            lobby.room['map'] = 'Rollercoaster2026'
            lobby.room['blueSide'] = 'B'
            app.render(lobby.room)
            self.assertEqual(app.capture_toggle.cget('state'), 'disabled')
            self.assertEqual(app.blue_side.get(), 'Side B')
            lobby.room['playerId'] = 'two'
            app.render(lobby.room)
            self.assertEqual(app.flag_toggle.cget('state'), 'disabled')
            self.assertEqual(app.fall_toggle.cget('state'), 'disabled')
            self.assertEqual(app.bot_toggle.cget('state'), 'disabled')
            self.assertEqual(str(app.side_combo.cget('state')), 'disabled')
        finally:
            app.close()
            app.close_worker.join(2)

    def test_closing_starter_preserves_active_lobby_membership(self):
        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        app = Desktop(root, lobby, lambda _: FakeGame())
        lobby.room.update(phase='ready', match={'id': 'a'*32, 'status': 'ready'})
        app.render(lobby.room)
        app.close()
        app.close_worker.join(2)
        self.assertFalse(app.close_worker.is_alive())
        self.assertNotIn(('leave', {}), lobby.calls)

    def test_auto_join_waits_for_a_ready_assigned_match_and_attempts_once(self):
        root = tk.Tk()
        root.withdraw()
        lobby, game = FakeLobby(), FakeGame()
        attempts = []

        def start(*, expected_map, expected_match_id):
            attempts.append((expected_map, expected_match_id))
            raise CommunityError('Manual retry is available.')

        game.start = start
        app = Desktop(root, lobby, lambda _: game)
        try:
            deadline = time.monotonic() + 4

            def wait_until(predicate):
                while not predicate() and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.01)
                self.assertTrue(predicate())

            wait_until(lambda: app.capabilities_loaded and not app.busy)
            match = {'id': 'a'*32, 'status': 'ready'}
            lobby.room.update(phase='ready', match=match)
            app.render(lobby.room)
            app.maybe_auto_join()
            self.assertEqual(attempts, [])

            lobby.room['players'][0]['team'] = 'blue'
            app.watch_id = 'watch'
            app.maybe_auto_join()
            self.assertEqual(attempts, [])
            app.watch_id = None
            wait_until(lambda: len(attempts) == 1 and not app.busy)
            app.maybe_auto_join()
            self.assertEqual(attempts, [('Stonehenge', match['id'])])

            self.assertEqual(app.game_button.cget('state'), 'normal')
            app.game_button.invoke()
            wait_until(lambda: len(attempts) == 2 and not app.busy)
            self.assertEqual(attempts[1], attempts[0])
            lobby.room['match'] = {'id': 'b'*32, 'status': 'ready'}
            app.render(lobby.room)
            wait_until(lambda: len(attempts) == 3 and not app.busy)
            self.assertEqual(attempts[2], ('Stonehenge', 'b'*32))
        finally:
            app.close()
            root.update()

    def test_prepares_before_lobby_entry_only_after_service_confirms_support(self):
        class UnreadyLobby(FakeLobby):
            def capabilities(self):
                return {'matchStartEnabled': True, 'gameClientReady': False}

        class PreparingGame(FakeGame):
            def __init__(self):
                super().__init__()
                self.prepared = False
            def prepare(self):
                self.prepared = True
                return True

        root = tk.Tk(); root.withdraw()
        lobby, game = UnreadyLobby(), PreparingGame()
        app = Desktop(root, lobby, lambda _: game)
        try:
            end = time.monotonic() + 5
            while time.monotonic() < end and app.busy:
                root.update(); time.sleep(.02)
            self.assertFalse(app.busy)
            self.assertIsNone(app.room)
            self.assertIsNone(app.game)
            self.assertFalse(game.prepared)
            app.set_capabilities({'matchStartEnabled': True, 'gameClientReady': True})
            self.assertIsNone(app.room)
            self.assertIs(app.game, game)
            self.assertTrue(game.prepared)
            self.assertFalse(game.started)
            self.assertEqual(lobby.calls, [])
        finally:
            app.close()
        self.assertTrue(game.stopped)

    def test_lobby_entry_prepares_client_and_displays_server_and_client_progress(self):
        class PreparingGame(FakeGame):
            def __init__(self):super().__init__();self.prepared=False
            def prepare(self):self.prepared=True;return True
            def snapshot(self):
                state=super().snapshot()
                state['preparation']={'status':'ready','error':None,'progress':'Game files ready.'}
                return state
        root=tk.Tk();root.withdraw();lobby,game=FakeLobby(),PreparingGame()
        lobby.room['preparation']={'status':'ready','map':'Stonehenge','contentHash':'a'*64,'progress':None}
        app=Desktop(root,lobby,lambda _:game)
        try:
            end=time.monotonic()+5
            while time.monotonic()<end and app.busy:root.update();time.sleep(.02)
            app.render(lobby.room);root.update()
            self.assertTrue(game.prepared);self.assertFalse(game.started)
            self.assertIn('Server ready',app.phase.get())
            end=time.monotonic()+2
            while time.monotonic()<end and app.preparation.get()!='Game files ready.':root.update();time.sleep(.02)
            self.assertEqual(app.preparation.get(),'Game files ready.')
            self.assertEqual(str(app.blue_button['state']),'normal')
            self.assertEqual(str(app.map_combo['state']),'readonly')
        finally:app.close()

    def test_packaged_map_label_selection_sends_identity_and_excludes_unavailable_weather(self):
        root=tk.Tk();root.attributes('-alpha',0);lobby,game=FakeLobby(),FakeGame()
        lobby.room['availableMaps']=options(('Stonehenge','Snowblind','Rollercoaster','Damnation','HighOctane','Scarabrae'))
        app=Desktop(root,lobby,lambda _:game)
        try:
            end=time.monotonic()+5
            while time.monotonic()<end and app.busy:
                root.update();time.sleep(.02)
            self.assertFalse(app.busy)
            app.render(lobby.room)
            root.update_idletasks();root.update()
            self.assertIn('High Octane',tuple(app.map_combo['values']))
            self.assertNotIn('Snowblind (weather)',tuple(app.map_combo['values']))
            app.map_name.set('High Octane');app.map_combo.event_generate('<<ComboboxSelected>>')
            end=time.monotonic()+5
            while time.monotonic()<end and ('map',{'map':'HighOctane'}) not in lobby.calls:
                root.update();time.sleep(.02)
            self.assertIn(('map',{'map':'HighOctane'}),lobby.calls)
        finally: app.close()

    def test_host_catalog_adds_an_unknown_map_to_the_picker(self):
        root = tk.Tk(); root.withdraw()
        lobby = FakeLobby()
        maps = options(('Stonehenge',)) + [{'id': 'NewMap', 'label': 'New Map'}]
        lobby.capabilities = lambda: {'mapFileSync': 2, 'maps': maps, 'matchStartEnabled': True, 'gameClientReady': True}
        lobby.room['availableMaps'] = maps
        app = Desktop(root, lobby, lambda _: FakeGame())
        try:
            deadline = time.monotonic() + 5
            while app.busy and time.monotonic() < deadline:
                root.update(); time.sleep(.02)
            app.render(lobby.room)
            self.assertIn('New Map', app.map_combo['values'])
            app.map_name.set('New Map')
            app.choose_map()
            while app.busy and time.monotonic() < deadline:
                root.update(); time.sleep(.02)
            self.assertIn(('map', {'map': 'NewMap'}), lobby.calls)
            self.assertEqual(app.map_name.get(), 'New Map')
        finally:
            app.close()

    def test_saved_steam_name_allows_lobby_entry_while_timeout_retries_in_background(self):
        folder = self.enterContext(TemporaryDirectory())
        settings = Path(folder)
        save_local_name(settings/'steam-persona.json', 'Saved Pilot')
        root=tk.Tk();root.withdraw()
        lobby,game=FakeLobby(),FakeGame()
        release_probe = Event()
        attempts = []
        def probe():
            attempts.append(True)
            if len(attempts) == 1:
                release_probe.wait(5)
                raise SteamIdentityError('Steam name lookup timed out.', reason='timeout')
            return 'Newest Steam'
        app=Desktop(root,lobby,lambda _:game,steam_name_loader=probe,name_settings_dir=settings)
        def wait(predicate):
            end=time.monotonic()+5
            while time.monotonic()<end:
                root.update()
                if predicate(): return
                time.sleep(.02)
            self.fail('Steam name UI operation did not complete')
        try:
            wait(lambda:not app.busy and app.name.get()=='Saved Pilot')
            self.assertEqual(str(app.name_entry['state']),'readonly')
            app.create_button.invoke()
            wait(lambda:not app.busy and app.room is not None)
            self.assertIn(('create','Saved Pilot'),lobby.calls)
            self.assertTrue(app.steam_lookup_running)
            with self.assertLogs('desktop_launcher', level='WARNING') as logs:
                release_probe.set()
                wait(lambda:app.steam_retry_handle is not None)
            self.assertIn('(timeout)', logs.output[0])
            self.assertNotIn('timed out', app.status.get())
            wait(lambda:app.name.get()=='Newest Steam')
            self.assertEqual(len(attempts), 2)
            self.assertEqual(read_local_name(settings/'steam-persona.json'), 'Newest Steam')
            app.render(None);app.code.set('abc234');app.join_button.invoke()
            wait(lambda:not app.busy and app.room is not None)
            self.assertIn(('join','ABC234','Newest Steam'),lobby.calls)
        finally:
            release_probe.set()
            app.close()
            app.close_worker.join(2)

    @unittest.skipUnless(sys.platform == 'win32', 'Warrior Name is in Windows Starter Settings.')
    def test_warrior_name_setting_validates_persists_and_can_be_cleared(self):
        settings = Path(self.enterContext(TemporaryDirectory()))
        save_local_name(settings/'warrior-name.json', 'Saved Warrior')
        save_local_name(settings/'steam-persona.json', 'Saved Persona')
        root=tk.Tk();root.withdraw()
        lobby=FakeLobby()
        app=Desktop(root,lobby,lambda _:FakeGame(),steam_name_loader=lambda:'Live Persona',
                    name_settings_dir=settings)
        try:
            self.assertFalse(app.steam_lookup_running)
            self.assertEqual(app.player_name_for_action(), 'Saved Warrior')
            app.show_settings()
            widgets = app.settings_window.winfo_children()
            entry = next(widget for widget in widgets if isinstance(widget, tk.Entry))
            save = next(widget for widget in widgets if isinstance(widget, tk.Button)
                        and widget.cget('text') == 'Save name')
            entry.delete(0, tk.END)
            entry.insert(0, 'A'*129)
            save.invoke()
            self.assertEqual(read_local_name(settings/'warrior-name.json'), 'Saved Warrior')
            entry.delete(0, tk.END)
            entry.insert(0, 'PÃ­lÃ¸t ðŸš€')
            save.invoke()
            self.assertEqual(app.player_name_for_action(), 'PÃ­lÃ¸t ðŸš€')
            self.assertEqual(read_local_name(settings/'warrior-name.json'), 'PÃ­lÃ¸t ðŸš€')
            entry.delete(0, tk.END)
            save.invoke()
            self.assertEqual(app.player_name_for_action(), 'Saved Persona')
            self.assertEqual(read_local_name(settings/'warrior-name.json'), '')
        finally:
            app.close()
            app.close_worker.join(2)

    def test_previous_preparation_failure_does_not_return_after_map_change(self):
        root = tk.Tk()
        root.withdraw()
        lobby, game = FakeLobby(), FakeGame()
        app = Desktop(root, lobby, lambda _: game)
        problem = 'Could not stage the old map.'
        try:
            app.render(lobby.room)
            app.game = game
            game.snapshot = Mock(return_value={
                'status': 'failed', 'error': problem, 'run': None,
                'preparation': {'error': problem},
            })
            if app.poll_handle is not None:
                root.after_cancel(app.poll_handle)
            app.poll()
            self.assertEqual(app.status.get(), problem)
            self.assertEqual(app.preparation.get(), problem)
            app.render(dict(lobby.room, map='Rollercoaster'))
            if app.poll_handle is not None:
                root.after_cancel(app.poll_handle)
            app.poll()
            self.assertEqual(app.status.get(), '')
            self.assertEqual(app.preparation.get(), '')

            app.call_action('start')
            self.assertEqual(app.status.get(), 'Starting match…')
            game.snapshot.return_value = {'status':'failed','error':'Current map failed.','run':None,
                                          'preparation':{'error':'Current map failed.'}}
            if app.poll_handle is not None:
                root.after_cancel(app.poll_handle)
            app.poll()
            self.assertIn('Current map failed.', app.status.get())
            self.assertEqual(app.preparation.get(), 'Current map failed.')
        finally:
            app.close()

    def test_match_status_and_roster_use_utf8_punctuation(self):
        self.assertEqual(match_phase_text({'phase': 'starting', 'match': {'progress': 'Loading replacement map'},
            'restart': {'stage': 'starting', 'reason': 'Player dropped', 'replacementMatchId': 'replacement'}}),
            'Match restarting · Player dropped — Loading replacement map')
        source = Path(__file__).with_name('desktop_launcher.py').read_text(encoding='utf-8')
        self.assertNotIn('\u00e2\u20ac', source)
        self.assertNotIn('\u00c2\u00b7', source)
        self.assertEqual(match_phase_text({'phase':'starting','match':{'progress':'Preparing the server runtime'}}),
                         'Match: starting \u2014 Preparing the server runtime')
        self.assertEqual(match_phase_text({'phase':'setup','preparation':{'status':'waiting'}}),
                         'Match: setup \u2014 Waiting for a server slot\u2026')
        root = tk.Tk()
        root.attributes('-alpha', 0)
        lobby, game = FakeLobby(), FakeGame()
        lobby.room['players'][0].update(name='Andr\u00e9',team='blue')
        app = Desktop(root, lobby, lambda _: game)
        try:
            app.render(lobby.room)
            self.assertEqual(app.rosters['blue'].get(0), 'Andr\u00e9  \u2022 leader  \u2022 you')
        finally:
            app.close()

    def test_roster_refresh_preserves_selected_player_and_scroll(self):
        root=tk.Tk();root.attributes('-alpha',0);root.geometry('850x650')
        lobby,game=FakeLobby(),FakeGame()
        lobby.room['players']=[{'id':str(i),'name':'Pilot '+str(i),'team':'blue' if i%2 else 'red','leader':i==0} for i in range(24)]
        lobby.room['playerId']='0'
        app=Desktop(root,lobby,lambda _:game)
        try:
            app.render(lobby.room);root.update()
            red = app.rosters['red']
            red.selection_set(10);red.see(10);root.update()
            before=red.yview()[0]
            updated=dict(lobby.room,players=list(reversed([dict(p) for p in lobby.room['players']])))
            app.render(updated);root.update()
            selected=red.curselection()
            self.assertEqual(len(selected),1)
            self.assertEqual(app.selected_player(),'20')
            self.assertAlmostEqual(red.yview()[0],before,delta=0.05)
            self.assertTrue(red.cget('yscrollcommand'))
            self.assertLess(app.rosters['blue'].winfo_rootx(), red.winfo_rootx())
        finally:
            app.close()

    def test_phoenix_lobby_create_uses_visible_map_and_disables_both_buttons(self):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        lobby = FakeLobby()
        lobby.create = Mock(return_value=lobby.room)
        lobby.capabilities = lambda: {'mapSessionSync': 3, 'matchStartEnabled': True}
        app = Desktop(root, lobby, lambda _: FakeGame())
        try:
            root.title('Tribes Rivals: Clan Wars (community mod)')
            root.update()
            self.assertEqual(root.title(), 'Tribes 3 Mod Community Edition: Phoenix Rising')
            deadline = time.monotonic() + 4
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertTrue(app.lobby_create_button.winfo_ismapped())
            self.assertEqual(app.map_combo.get(), app.create_map.get())
            selected = next(row for row in app.map_options if row['id'] == 'Rollercoaster')
            app.map_combo.set(selected['label'])
            app.name.set('Pilot')
            app.lobby_create_button.invoke()
            deadline = time.monotonic() + 4
            while app.room is None and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            lobby.create.assert_called_once_with('Pilot', map_id='Rollercoaster')
            self.assertIsNotNone(app.room)
            for button in (app.lobby_create_button, app.create_button):
                self.assertEqual(str(button.cget('state')), 'disabled')
            for team, faction in [('blue', 'Children of The Phoenix'), ('red', 'Diamond Sword')]:
                self.assertEqual(app.live_roster_table.heading(team, 'text'), faction)
                self.assertIn(faction, [w.cget('text') for w in app.rosters[team].master.winfo_children()
                                        if isinstance(w, tk.Label)])
        finally:
            app.close()

    def test_controls_fit_at_declared_minimum_window_size(self):
        root=tk.Tk();root.attributes('-alpha',0)
        lobby,game=FakeLobby(),FakeGame()
        app=Desktop(root,lobby,lambda _:game)
        try:
            root.geometry('%dx%d' % root.minsize())
            lobby.room['blueSide'] = 'B'
            app.caps['matchRulesEnabled'] = True
            app.render(lobby.room)
            app.status.set('Community service connected.')
            root.update_idletasks();root.update()
            width,height=root.winfo_width(),root.winfo_height()
            status=next(child for child in app.lobby_panel.pack_slaves()
                        if isinstance(child,tk.Label) and str(child.cget('textvariable'))==str(app.status))
            widgets=(app.name_entry,app.code_entry,app.join_button,app.map_combo,
                     app.side_combo,*app.rosters.values(),app.blue_button,app.red_button,app.move_blue,app.move_red,
                     app.start_button,app.game_button,app.stop_button,app.reset_button,app.leave_button,status)
            self.assertGreaterEqual(status.winfo_height(),status.winfo_reqheight())
            for widget in widgets:
                self.assertTrue(widget.winfo_ismapped(), str(widget))
                right=widget.winfo_rootx()-root.winfo_rootx()+widget.winfo_width()
                bottom=widget.winfo_rooty()-root.winfo_rooty()+widget.winfo_height()
                self.assertLessEqual(right,width, str(widget))
                self.assertLessEqual(bottom,height, str(widget))
                parent=widget.master
                while parent is not root:
                    right_in_parent=widget.winfo_rootx()-parent.winfo_rootx()+widget.winfo_width()
                    bottom_in_parent=widget.winfo_rooty()-parent.winfo_rooty()+widget.winfo_height()
                    self.assertLessEqual(right_in_parent,parent.winfo_width(), str(widget))
                    self.assertLessEqual(bottom_in_parent,parent.winfo_height(), str(widget))
                    parent=parent.master
            app.show_panel('live')
            root.update_idletasks()
            self.assertTrue(app.create_button.winfo_ismapped())
            self.assertLessEqual(app.create_button.winfo_rootx() + app.create_button.winfo_width(),
                                 root.winfo_rootx() + width)
        finally:
            app.close()

    def test_expired_session_returns_to_lobby_entry(self):
        root=tk.Tk();root.withdraw()
        lobby,game=FakeLobby(),FakeGame()
        app=Desktop(root,lobby,lambda _:game)
        def wait(predicate):
            end=time.monotonic()+5
            while time.monotonic()<end:
                root.update()
                if predicate(): return
                time.sleep(.02)
            self.fail('Desktop operation did not complete')
        try:
            wait(lambda:not app.busy)
            app.name.set('One');app.create_button.invoke()
            wait(lambda:not app.busy and app.room is not None)
            def expired(*args,**kwargs): raise CommunityError('Lobby expired',code='lobby_missing')
            lobby.action=expired
            app.call_action('state')
            wait(lambda:not app.busy and app.room is None)
            self.assertEqual(str(app.create_button['state']),'normal')
            self.assertEqual(app.status.get(),'Lobby expired')
        finally:
            app.close()

    def test_lobby_controls_and_join_game(self):
        root=tk.Tk();root.withdraw()
        lobby,game=FakeLobby(),FakeGame()
        app=Desktop(root,lobby,lambda _:game)
        def wait(predicate):
            end=time.monotonic()+5
            while time.monotonic()<end:
                root.update()
                if predicate(): return
                time.sleep(.02)
            self.fail('Desktop operation did not complete')
        try:
            wait(lambda:not app.busy)
            app.name.set('One')
            app.create_button.invoke()
            wait(lambda:not app.busy and app.room is not None)
            self.assertEqual(lobby.calls[0],('create','One'))
            app.red_button.invoke()
            wait(lambda:not app.busy and app.players[0]['team']=='red')
            app.rosters[None].selection_set(0)
            app.move_blue.invoke()
            wait(lambda:not app.busy and app.players[1]['team']=='blue')
            app.call_action('map',map='Snowblind')
            wait(lambda:not app.busy and app.map_name.get()=='Snowblind (clear)')
            app.start_button.invoke()
            wait(lambda:not app.busy and app.room['phase']=='ready')
            self.assertEqual(str(app.game_button['state']),'normal')
            app.game_button.invoke()
            wait(lambda:not app.busy and game.started)
        finally:
            app.close()
        self.assertTrue(game.stopped)


if __name__ == '__main__':
    unittest.main(verbosity=2)
