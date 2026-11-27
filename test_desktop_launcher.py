"""Exercise desktop controls with a fake lobby and game, without network or game launch."""
import time
import gc
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

from desktop_launcher import Desktop
from community_transport import CommunityError, LOBBY_LOCK_RULES_ENABLED, RESULT_STATS
from community_maps import options


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
        elif operation == 'rules' and 'locked' in data:
            self.room['locked'] = data['locked']
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

    def test_match_results_show_final_scores_and_remain_available_in_setup(self):
        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        lobby.map_label = lambda _: 'Stonehenge'
        app = Desktop(root, lobby, lambda _: FakeGame())
        try:
            stats = dict.fromkeys(RESULT_STATS, 0)
            stats.update(kills=4, deaths=2, assists=1, captures=3,
                         returns=5, flagGrabs=7, flagHeldSeconds=65.9)
            match_id = '1' * 32
            result = {'matchId': match_id, 'map': 'Stonehenge', 'scores': {'blue': 3, 'red': 2},
                      'players': [{'name': 'One', 'team': 'blue', 'stats': stats}]}
            app.render(dict(lobby.room, phase='ended', match={'id': match_id}, lastResult=result))
            self.assertIn('Blue 3', app.phase.get())
            app.result_button.invoke()
            panel = app.result_window.winfo_children()[0]
            board = next(w for w in panel.winfo_children()[2].winfo_children() if w.winfo_class() == 'Treeview')
            self.assertEqual(board.item(board.get_children()[0], 'values'),
                             ('One', 'Blue', '4', '2', '1', '3', '5', '7', '1:05'))
            app.render(dict(lobby.room, lastResult=result))
            self.assertEqual(app.result_button.winfo_manager(), 'grid')
            app.render(dict(lobby.room, lastResult=dict(result, players=None)))
            self.assertFalse(app.result_button.winfo_manager())
        finally:
            app.close()
            app.close_worker.join(2)

    def test_private_restart_displays_countdown_and_hands_off_owned_client(self):
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
            original = 'a' * 32
            room = lobby.room
            room.update(phase='ready', match={'id': original, 'status': 'ready'})
            room['players'][0]['team'] = 'blue'
            app.render(room)
            self.assertEqual(app.restart_button.cget('state'), 'normal')
            with patch('desktop_launcher.simpledialog.askstring', return_value='Connection lost'), patch.object(app, 'call_action') as action:
                app.restart_button.invoke()
                action.assert_called_once_with('restart', matchId=original, reason='Connection lost')
            restart = {'stage': 'countdown', 'matchId': original, 'reason': 'Connection lost', 'seconds': 8}
            room['restart'] = restart
            own_game = {'status': 'playing', 'role': 'player', 'matchId': original, 'error': None}
            with patch.object(game, 'snapshot', return_value=own_game), patch.object(game, 'stop_replaced_match', return_value=True, create=True) as stop:
                for stage in ('countdown', 'draining'):
                    restart['stage'] = stage
                    app.render(room)
                    root.after_cancel(app.poll_handle)
                    app.poll()
                    self.assertEqual(app.game_button.cget('state'), 'disabled')
                    if stage == 'countdown':
                        self.assertIn('8s · Connection lost', app.phase.get())
                        stop.assert_not_called()
                stop.assert_called_once_with(original)
            restart.update(stage='complete', replacementMatchId='b' * 32)
            room['match'] = {'id': 'b' * 32, 'status': 'ready'}
            app.join_attempted_match = original
            app.render(room)
            with patch.object(app, 'join_game') as join:
                root.after_cancel(app.poll_handle)
                app.poll()
                join.assert_called_once()
        finally:
            app.close()
            app.close_worker.join(2)

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
            app.name.set('Player')
            with patch.object(app, 'run_async') as enter, patch.object(lobby, 'create') as create:
                app.create()
                enter.call_args.args[0]()
                create.assert_called_once_with('Player', locked=True)
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
            with patch.object(app, 'run_async') as enter, patch.object(lobby, 'join_match', create=True) as join:
                app.join_live_selected()
                enter.call_args.args[0]()
                join.assert_called_once_with(match_id, 'Player', team='red')
        finally:
            app.close()
            app.close_worker.join(2)

    def test_advanced_rules_lock_checkbox_uses_lobby_state_and_leader_permissions(self):
        root = tk.Tk()
        root.withdraw()
        lobby = FakeLobby()
        app = Desktop(root, lobby, lambda _: FakeGame())

        def wait_idle():
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertFalse(app.busy)

        try:
            wait_idle()
            app.caps['privateLobbyAdmission'] = True
            lobby.room['locked'] = True
            app.render(lobby.room)
            self.assertFalse(app.room_lock_toggle.winfo_manager())
            app.caps[LOBBY_LOCK_RULES_ENABLED] = True
            app.render(lobby.room)
            app.advanced_button.invoke()
            self.assertEqual(app.rules_row.winfo_manager(), 'pack')
            self.assertEqual(app.room_lock_toggle.cget('state'), 'normal')
            self.assertTrue(app.room_locked.get())
            self.assertNotIn('Locked', app.room_heading.get())

            app.room_lock_toggle.invoke()
            self.assertEqual(app.start_button.cget('state'), 'disabled')
            wait_idle()
            self.assertIn(('rules', {'locked': False}), lobby.calls)
            self.assertFalse(app.room_locked.get())

            app.render(dict(lobby.room, playerId='two', locked=True))
            self.assertTrue(app.room_locked.get())
            self.assertEqual(app.room_lock_toggle.cget('state'), 'disabled')
            app.render(dict(lobby.room, phase='starting', locked=True))
            self.assertIn('Locked', app.room_heading.get())
            self.assertEqual(app.room_lock_toggle.cget('state'), 'disabled')
        finally:
            app.close()
            app.close_worker.join(2)

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
            self.assertFalse(app.rules_row.winfo_manager())
            app.advanced_button.invoke()
            self.assertEqual(app.rules_row.winfo_manager(), 'pack')
            self.assertFalse(app.fall_toggle.winfo_manager())
            self.assertFalse(app.limits_row.winfo_manager())
            app.caps['matchLimitsEnabled'] = True
            app.render(lobby.room)
            self.assertEqual(app.limits_row.winfo_manager(), 'grid')
            self.assertEqual(app.score_limit.get(), 'Map default')
            self.assertEqual(str(app.score_limit.cget('state')), 'readonly')
            app.score_limit.set('Unlimited')
            app.match_minutes.set('21')
            limits = {'scoreLimit': 0, 'matchMinutes': 21}
            with patch.object(app, 'call_action') as call:
                app.change_match_limits()
                call.assert_called_once_with('rules', matchLimits=limits)
            lobby.room['matchLimits'] = limits
            app.render_live_matches([{'id': '1'*32, 'label': 'Katabatic', 'playerCount': 1,
                                      'playerCapacity': 24, 'spectatorCount': 0,
                                      'spectatorCapacity': 25, 'matchLimits': limits}])
            self.assertEqual(app.live_list.item('1'*32, 'values')[-1], 'Unlimited / 21 min')
            app.caps['fallDamageEnabled'] = True
            lobby.room['rules']['fallDamage'] = True
            app.render(lobby.room)
            self.assertEqual(app.fall_toggle.winfo_manager(), 'grid')
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
            self.assertEqual(str(app.score_limit.cget('state')), 'disabled')
            self.assertEqual(app.score_limit.get(), 'Unlimited')
            self.assertEqual(app.match_minutes.get(), '21')
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

    def test_steam_name_is_readonly_and_refreshed_before_lobby_entry(self):
        root=tk.Tk();root.withdraw()
        lobby,game=FakeLobby(),FakeGame()
        names=iter(('Initial Steam','Current Steam','Newest Steam'))
        app=Desktop(root,lobby,lambda _:game,steam_name_loader=lambda:next(names))
        def wait(predicate):
            end=time.monotonic()+5
            while time.monotonic()<end:
                root.update()
                if predicate(): return
                time.sleep(.02)
            self.fail('Steam name UI operation did not complete')
        try:
            wait(lambda:not app.busy and app.name.get()=='Initial Steam')
            self.assertEqual(str(app.name_entry['state']),'readonly')
            app.create_button.invoke()
            wait(lambda:not app.busy and app.room is not None)
            self.assertIn(('create','Current Steam'),lobby.calls)
            app.render(None);app.code.set('abc234');app.join_button.invoke()
            wait(lambda:not app.busy and app.name.get()=='Newest Steam')
            self.assertIn(('join','ABC234','Newest Steam'),lobby.calls)
        finally: app.close()

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

    def test_controls_fit_at_declared_minimum_window_size(self):
        root=tk.Tk();root.attributes('-alpha',0)
        lobby,game=FakeLobby(),FakeGame()
        caps = dict(matchRulesEnabled=True, matchLimitsEnabled=True, fallDamageEnabled=True, spectateEnabled=True,
                    matchRestartEnabled=True)
        lobby.capabilities = lambda: caps
        app=Desktop(root,lobby,lambda _:game)
        try:
            root.geometry('%dx%d' % root.minsize())
            lobby.room['blueSide'] = 'B'
            app.caps = caps
            app.render(lobby.room)
            app.status.set('Community service connected.')
            root.update_idletasks();root.update()
            width,height=root.winfo_width(),root.winfo_height()
            status = app.room_status
            self.assertFalse(app.name_entry.winfo_ismapped())
            self.assertFalse(app.flag_toggle.winfo_ismapped())
            app.advanced_button.invoke()
            app.render(lobby.room)
            root.update()
            widgets=(app.entry_toggle, app.map_combo, app.side_combo, app.score_limit, app.match_minutes,
                     app.flag_toggle, app.fall_toggle, app.bot_spinner, app.capture_toggle, app.spectator_toggle,
                     *app.rosters.values(),app.blue_button,app.red_button,app.move_blue,app.move_red,
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
            lobby.room['phase'] = 'ready'
            app.caps['matchRestartEnabled'] = True
            app.render(lobby.room)
            root.update()
            self.assertTrue(app.restart_button.winfo_ismapped())
            app.entry_toggle.invoke()
            root.update()
            self.assertTrue(app.name_entry.winfo_ismapped())
            self.assertTrue(app.leave_button.winfo_ismapped())
            app.render(None)
            root.update()
            self.assertTrue(app.join_button.winfo_ismapped())
            self.assertFalse(app.advanced_button.winfo_ismapped())
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
