"""Real ZIP hashing and map-catalog matching with synthetic player-package bytes."""
import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from tools.verify_player_release import map_catalog,verify
from map_catalog import verified_catalog

class PlayerReleaseTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.files={'client.py':b'pass\n','community_starter.pyw':b'pass\n','Start Community Starter.vbs':b'fixture','python/pythonw.exe':b'fixture-runtime','lua/client.lua':b'return {}\n','README-FIRST.txt':b'Synthetic fixture only','base-game-manifest.json':b'{"files":[]}', 'content/Maps/Community/Snowblind/Arena_Snowblind_P.umap':b'fixture-map','content/Maps/Community/Snowblind/Arena_Snowblind_P.uexp':b'fixture-exports','content/Community/Snowblind/fixture.uasset':b'fixture-asset'}
  self.rebuild()
 def rebuild(self):
  rows=[{'path':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}for n,b in self.files.items()if n!='RELEASE-INFO.json']
  self.manifest={'community_maps':['Snowblind'],'map_runtime':{'Snowblind':[]},'shared_content':{},'files':rows}
  self.catalog=map_catalog(self.manifest)
  self.files['RELEASE-INFO.json']=json.dumps({'release':'synthetic-test','verified_map_catalog':self.catalog}).encode()
  b=self.files['RELEASE-INFO.json'];rows.append({'path':'RELEASE-INFO.json','bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
  self.server=self.root/'server.json';self.server.write_text(json.dumps({'verified_map_catalog':self.catalog,'host_manifest_sha256':'a'*64}))
 def archive(self,changes=None,extra=None):
  path=self.root/'player.zip'
  with zipfile.ZipFile(path,'w')as z:
   for n,b in self.files.items():z.writestr('Client/'+n,(changes or{}).get(n,b))
   z.writestr('Client/package-manifest.json',json.dumps(self.manifest))
   if extra:z.writestr(extra,b'unexpected')
  return path
 def test_real_hash_audit_and_catalog_match(self):
  report=verify(self.archive(),self.server,self.root/'proof')
  self.assertTrue(report['passed']);self.assertEqual(report['verified_members'],len(self.files))
 def test_stream_catalog_equals_existing_directory_verifier(self):
  package=self.root/'package';package.mkdir()
  for n,b in self.files.items():
   p=package/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
  (package/'package-manifest.json').write_text(json.dumps(self.manifest))
  self.assertEqual(map_catalog(self.manifest),verified_catalog(package))
 def test_tampered_payload_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):verify(self.archive({'content/Community/Snowblind/fixture.uasset':b'tampered-data'}),self.server,self.root/'proof')
 def test_wrong_server_map_version_is_rejected(self):
  self.server.write_text(json.dumps({'verified_map_catalog':{'Snowblind':'b'*64}}))
  with self.assertRaisesRegex(ValueError,'do not match'):verify(self.archive(),self.server,self.root/'proof')
 def test_unlisted_or_escaping_members_are_rejected(self):
  for extra in ('Client/unlisted.txt','Client/../../outside.txt'):
   with self.assertRaisesRegex(ValueError,'differs'):verify(self.archive(extra=extra),self.server,self.root/'proof')
 def test_private_key_cannot_be_added_to_declared_inventory(self):
  self.files['private/server.key']=b'fixture';self.rebuild()
  with self.assertRaisesRegex(ValueError,'Private/original-game'):verify(self.archive(),self.server,self.root/'proof')

if __name__=='__main__':unittest.main()
