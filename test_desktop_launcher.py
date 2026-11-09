"""Exercise desktop controls with a fake lobby and game, without network or game launch."""
import time
import gc
import tkinter as tk
import unittest

from desktop_launcher import Desktop
from community_transport import CommunityError
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
            app.roster.selection_set(20);app.roster.see(20);root.update()
            before=app.roster.yview()[0]
            updated=dict(lobby.room,players=list(reversed([dict(p) for p in lobby.room['players']])))
            app.render(updated);root.update()
            selected=app.roster.curselection()
            self.assertEqual(len(selected),1)
            self.assertEqual(app.players[selected[0]]['id'],'20')
            self.assertAlmostEqual(app.roster.yview()[0],before,delta=0.05)
            self.assertTrue(app.roster.cget('yscrollcommand'))
        finally:
            app.close()

    def test_controls_fit_at_declared_minimum_window_size(self):
        root=tk.Tk();root.attributes('-alpha',0)
        lobby,game=FakeLobby(),FakeGame()
        app=Desktop(root,lobby,lambda _:game)
        try:
            root.geometry('%dx%d' % root.minsize())
            app.render(lobby.room)
            app.status.set('Community service connected.')
            root.update_idletasks();root.update()
            width,height=root.winfo_width(),root.winfo_height()
            status=next(child for child in app.lobby_panel.pack_slaves()
                        if isinstance(child,tk.Label) and str(child.cget('textvariable'))==str(app.status))
            widgets=(app.name_entry,app.code_entry,app.create_button,app.join_button,app.map_combo,
                     app.roster,app.blue_button,app.red_button,app.move_blue,app.move_red,
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
            app.roster.selection_set(1)
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
