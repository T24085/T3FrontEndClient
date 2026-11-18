"""Owned preparer handoff and cancellation without starting a game."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from community_game import CommunityGame
from community_transport import CommunityError

class Lobby:
 test_source=None
 def __init__(self):self.map='Stonehenge';self.calls=0
 def match_target(self):
  self.calls+=1
  return {'map':self.map,'contentHash':'a'*64,'matchId':'fixture','endpoint':'100.80.168.96:18000'}

class CommunityPreparationTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='tribes-prep-handoff-');root=Path(self.tmp.name).resolve()
  package=root/'package';(package/'lib').mkdir(parents=True);source=root/'source';source.mkdir()
  (package/'package-manifest.json').write_text(json.dumps({'startup_contract':'prepared-client-v1'}))
  (package/'lib/owned_native_session.py').write_text('def run_owned_job(*a,**k):raise AssertionError("unused fixture")')
  self.lobby=Lobby();self.game=CommunityGame(self.lobby,package,source,root/'workspace',root/'control')
  self.calls=[];self.gate=threading.Event();self.entered=threading.Event()
 def tearDown(self):
  self.gate.set()
  if self.game.preparation_thread:self.game.preparation_thread.join(5)
  if self.game.thread:self.game.thread.join(5)
  self.tmp.cleanup()
 def ready_owner(self,argv,cwd,env,artifacts,**kwargs):
  self.calls.append(argv)
  if '--prepare-only'in argv:
   self.entered.set();self.gate.wait(5)
   run=self.game.workspace/f'client-{len(self.calls):012x}';run.mkdir();path=run/'prepared.json';path.write_text('{}')
   descriptor={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
   artifacts.mkdir(parents=True);(artifacts/'stdout.log').write_text('CLIENT_PREPARED|'+json.dumps(descriptor)+'\n')
   return {'status':'terminal','exit_code':0,'job_active_processes_after_cleanup':0}
  return {'status':'terminal','exit_code':1,'job_active_processes_after_cleanup':0}
 def test_prepares_without_endpoint_then_join_passes_authenticated_match_and_descriptor(self):
  self.game.owner.run_owned_job=self.ready_owner
  self.assertTrue(self.game.prepare());self.assertTrue(self.entered.wait(2))
  self.assertEqual(self.lobby.calls,0);self.assertEqual(len(self.calls),1)
  self.assertNotIn('--endpoint',self.calls[0]);self.assertTrue(self.game.prepare())
  self.assertEqual(self.game.snapshot()['status'],'idle')
  self.gate.set();self.game.preparation_thread.join(3)
  self.assertEqual(self.game.preparation_snapshot()['status'],'ready')
  self.game.start();self.game.wait(3)
  self.assertEqual(len(self.calls),2)
  self.assertIn('--prepared',self.calls[1]);self.assertIn('--prepared-sha256',self.calls[1])
  self.assertEqual(self.calls[1][self.calls[1].index('--expected-map')+1],'Stonehenge')
  self.assertEqual(self.lobby.calls,2);self.assertEqual(self.game.preparation_status,'spent')
 def test_close_cancels_owned_preparation_and_never_launches_game(self):
  self.game.owner.run_owned_job=self.ready_owner;self.game.prepare();self.assertTrue(self.entered.wait(2))
  self.game.stop();self.gate.set();self.game.preparation_thread.join(3)
  self.assertEqual(self.game.preparation_status,'stopped')
  self.assertTrue((self.game.preparation_artifacts/'stop.json').is_file())
  self.assertEqual(len(self.calls),1);self.assertIsNone(self.game.thread)
 def test_join_replaces_prewarmed_files_when_match_requires_downloaded_revision(self):
  revision='b'*64
  self.game.map_sync=SimpleNamespace(current=(None,{}),status='',revision_for=lambda *_:revision)
  self.game.owner.run_owned_job=self.ready_owner
  self.game.prepare();self.assertTrue(self.entered.wait(2));self.gate.set();self.game.preparation_thread.join(3)
  self.game.start();self.game.wait(3)
  self.assertEqual(len(self.calls),3)
  self.assertNotIn('--map-revision',self.calls[0])
  self.assertEqual(self.calls[1][self.calls[1].index('--map-revision')+1],revision)
  self.assertIn('client-000000000002',self.calls[2][self.calls[2].index('--prepared')+1])
 def test_unconfirmed_preparer_cleanup_retains_quarantine_and_blocks_retries(self):
  self.game.owner.run_owned_job=lambda *a,**k:{'status':'terminal','exit_code':0,'job_active_processes_after_cleanup':1}
  self.game.prepare();self.game.preparation_thread.join(3)
  self.assertEqual(self.game.preparation_status,'quarantined');self.assertFalse(self.game.prepare())
  with self.assertRaisesRegex(CommunityError,'cleanup'):self.game.start()
  self.assertIsNone(self.game.thread)
 def test_changed_match_during_preparation_never_launches_join_child(self):
  self.game.owner.run_owned_job=self.ready_owner;self.game.prepare();self.assertTrue(self.entered.wait(2))
  failures=[]
  def join():
   try:self.game.start()
   except CommunityError as exc:failures.append(str(exc))
  joiner=threading.Thread(target=join);joiner.start()
  self.lobby.map='Snowblind';self.gate.set();joiner.join(5)
  self.assertEqual(len(self.calls),1);self.assertEqual(self.game.status,'failed')
  self.assertEqual(len(failures),1);self.assertIn('match changed',failures[0])
 def test_stop_while_join_waits_for_preparation_prevents_join_child(self):
  self.game.owner.run_owned_job=self.ready_owner
  joiner=threading.Thread(target=self.game.start);joiner.start();self.assertTrue(self.entered.wait(2))
  self.game.stop();self.gate.set();joiner.join(5)
  self.assertEqual(len(self.calls),1);self.assertEqual(self.game.status,'stopped');self.assertIsNone(self.game.thread)

if __name__=='__main__':unittest.main()
