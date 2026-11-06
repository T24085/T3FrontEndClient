"""Real complete-ZIP rebuilds with frozen maps and coordinated source overlays."""
import hashlib,json,unittest,zipfile
from pathlib import Path
import test_player_release as fixtures
from tools.build_player_release import build,SOURCE_MEMBERS
from tools.verify_player_release import verify

class CompleteReleaseBuildTests(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.PlayerReleaseTests('test_real_hash_audit_and_catalog_match');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  self.base=self.fixture.archive();self.digest=hashlib.sha256(self.base.read_bytes()).hexdigest()
  self.source=self.fixture.root/'source';self.source.mkdir();(self.source/'client_entry.py').write_bytes(b'# current source\npass\n')
 def build(self,**kwargs):
  options=dict(source=self.source,frontend_ref='a'*40,backend_ref='b'*40,tag='windows-test-r6',release_id='test-r6',archive_name='player-r6.zip',source_members={'client.py':'client_entry.py'})
  options.update(kwargs)
  return build(self.base,self.digest,self.fixture.server,self.fixture.root/'release',**options)
 def test_complete_rebuild_preserves_maps_and_verifies_every_new_member(self):
  archive=self.build();report=verify(archive,self.fixture.server,self.fixture.root/'verification')
  self.assertTrue(report['server_map_match'])
  with zipfile.ZipFile(archive)as z:
   self.assertEqual(z.read('TRIBES3-Community-Starter/client.py'),(self.source/'client_entry.py').read_bytes())
   for name,data in self.fixture.files.items():
    if name.startswith('content/'):self.assertEqual(z.read('TRIBES3-Community-Starter/'+name),data)
   info=json.loads(z.read('TRIBES3-Community-Starter/SOURCE-INFO.json'))
   self.assertEqual(info['source_commits'],{'frontend':'a'*40,'backend':'b'*40})
   self.assertEqual(info['base_archive_sha256'],self.digest)
 def test_bad_base_digest_is_rejected_before_output_is_created(self):
  self.digest='0'*64
  with self.assertRaisesRegex(ValueError,'Base archive SHA256 mismatch'):self.build()
  self.assertFalse((self.fixture.root/'release').exists())
 def test_release_includes_current_client_lua_and_explicit_release_notes(self):
  self.assertEqual(SOURCE_MEMBERS['lua/client.lua'],'lua/client.lua')
  path=self.source/'lua/client.lua';path.parent.mkdir();path.write_text('-- current Heavy Bolt runtime\n')
  readme=self.source/'release-readme.txt';readme.write_text('R7 playtest: visual confirmation pending.\n')
  archive=self.build(source_members={'lua/client.lua':'lua/client.lua'},readme=readme,
                     known_issues=['Heavy Bolt whiteout needs visual confirmation.'])
  report=verify(archive,self.fixture.server,self.fixture.root/'verification');self.assertTrue(report['passed'])
  with zipfile.ZipFile(archive)as z:
   self.assertEqual(z.read('TRIBES3-Community-Starter/lua/client.lua'),path.read_bytes())
   self.assertEqual(z.read('TRIBES3-Community-Starter/README-FIRST.txt'),readme.read_bytes())
   info=json.loads(z.read('TRIBES3-Community-Starter/RELEASE-INFO.json'))
   self.assertEqual(info['known_issues'],['Heavy Bolt whiteout needs visual confirmation.'])
 def test_source_cannot_replace_frozen_content(self):
  destination='content/Community/Snowblind/fixture.uasset'
  with self.assertRaisesRegex(ValueError,'payload is frozen'):self.build(source_members={destination:'client_entry.py'})
 def test_wrong_current_server_catalog_is_rejected(self):
  self.fixture.server.write_text(json.dumps({'verified_map_catalog':{'Snowblind':'f'*64}}))
  with self.assertRaisesRegex(ValueError,'differ from the verified server'):self.build()

if __name__=='__main__':unittest.main()
