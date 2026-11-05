"""Real Tk control state with delayed lobby replies; no native game or live server."""
import copy,gc,threading,time,tkinter as tk,unittest
from desktop_launcher import Desktop
from community_maps import BY_ID
from test_desktop_launcher import FakeLobby,FakeGame

class DesktopRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.root=tk.Tk();self.root.withdraw();self.lobby=FakeLobby();self.game=FakeGame()
  self.app=Desktop(self.root,self.lobby,lambda _:self.game)
  self.wait(lambda:not self.app.busy);self.app.render(copy.deepcopy(self.lobby.room))
 def tearDown(self):
  if not self.app.closing:self.app.close()
  self.app.close_worker.join(3);gc.collect()
 def wait(self,predicate):
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   self.root.update()
   if predicate():return
   time.sleep(.01)
  self.fail('UI operation did not finish')
 def choose(self,name):
  self.app.map_name.set(BY_ID[name].label);self.app.choose_map()
 def test_selection_while_refresh_is_busy_is_not_dropped_or_overwritten(self):
  entered,release=threading.Event(),threading.Event();old=copy.deepcopy(self.lobby.room)
  def refresh():entered.set();release.wait(3);return old
  self.app.run_async(refresh,self.app.render);self.assertTrue(entered.wait(2))
  try:
   self.choose('Snowblind');self.app.render(old)
   self.assertEqual(self.app.map_name.get(),BY_ID['Snowblind'].label)
   self.assertEqual(str(self.app.start_button['state']),'disabled')
   self.app.call_action('start');self.assertNotIn(('start',{}),self.lobby.calls)
  finally:release.set()
  self.wait(lambda:not self.app.busy and self.app.pending_map is None)
  self.assertIn(('map',{'map':'Snowblind'}),self.lobby.calls)
  self.assertEqual(self.app.room['map'],'Snowblind')
 def test_latest_of_rapid_map_choices_is_applied_after_first_reply(self):
  entered,release=threading.Event(),threading.Event();action=self.lobby.action
  def delayed(operation,**data):
   if operation=='map'and data['map']=='Snowblind':entered.set();release.wait(3)
   return copy.deepcopy(action(operation,**data))
  self.lobby.action=delayed;self.choose('Snowblind');self.assertTrue(entered.wait(2))
  try:
   self.choose('Rollercoaster');self.assertEqual(self.app.map_name.get(),BY_ID['Rollercoaster'].label)
  finally:release.set()
  self.wait(lambda:not self.app.busy and self.app.pending_map is None)
  self.assertEqual([data['map']for op,data in self.lobby.calls if op=='map'],['Snowblind','Rollercoaster'])
  self.assertEqual(self.app.room['map'],'Rollercoaster');self.assertEqual(self.app.map_name.get(),BY_ID['Rollercoaster'].label)
 def test_finished_lobby_can_be_left_without_new_setup(self):
  self.app.render(dict(self.lobby.room,phase='stopped'))
  self.assertEqual(str(self.app.leave_button['state']),'normal')
  self.app.leave_button.invoke();self.wait(lambda:not self.app.busy and self.app.room is None)
 def test_join_passes_the_displayed_map_to_game_owner(self):
  expected=[]
  def start(*,expected_map=None):expected.append(expected_map)
  self.game.start=start;self.app.render(dict(self.lobby.room,phase='ready'))
  self.app.join_game();self.wait(lambda:not self.app.busy)
  self.assertEqual(expected,['Stonehenge'])
 def test_close_releases_membership_without_blocking_tk(self):
  self.app.close();self.app.close_worker.join(3)
  self.assertFalse(self.app.close_worker.is_alive());self.assertIn(('leave',{}),self.lobby.calls)
 def test_capability_handshake_recovers_existing_lobby_without_creating_another(self):
  self.app.render(None);resumed=[]
  def resume():resumed.append(True);return copy.deepcopy(self.lobby.room)
  self.lobby.resume=resume
  self.app.set_capabilities({'matchStartEnabled':True,'gameClientReady':True,'lobbyResumeEnabled':True})
  self.wait(lambda:not self.app.busy and self.app.room is not None)
  self.assertEqual(resumed,[True]);self.assertFalse(any(op=='create'for op,*_ in self.lobby.calls))

if __name__=='__main__':unittest.main()
