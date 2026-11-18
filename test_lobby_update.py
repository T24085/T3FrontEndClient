import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools import apply_lobby_recovery_update as update

class UpdateTests(unittest.TestCase):
 def fixture(self,kind):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)/'app';payload=Path(temp.name)/'payload';root.mkdir();payload.mkdir();rows=[]
  for name in update.FILES[kind]:
   for folder,raw in ((root,b'old = True\n'),(payload,b'new = True\n')):
    p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
   raw=(root/name).read_bytes();rows.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
  mp=root/('package-manifest.json'if kind=='client'else'server-package-manifest.json')
  mp.write_text(json.dumps({'files':rows,'community_maps':['Snowblind'],'map_runtime':{'Snowblind':['lua/test.lua']},'shared_content':{}}))
  return root,payload,mp
 def test_client_and_server_update_keep_maps_and_are_idempotent(self):
  for kind in update.FILES:
   root,payload,mp=self.fixture(kind);result=update.apply(root,payload,kind)
   self.assertTrue(result['maps_unchanged']);self.assertTrue(Path(result['backup']).is_dir())
   self.assertEqual(json.loads(mp.read_bytes())['community_maps'],['Snowblind'])
   self.assertEqual(update.apply(root,payload,kind)['status'],'already_installed')
 def test_changed_installation_is_refused(self):
  root,payload,mp=self.fixture('client');before=mp.read_bytes();(root/'desktop_launcher.py').write_text('custom = True\n')
  with self.assertRaisesRegex(ValueError,'differs'):update.apply(root,payload,'client')
  self.assertEqual(mp.read_bytes(),before)
 def test_partial_write_rolls_back_all_payload_and_inventory(self):
  root,payload,mp=self.fixture('client');before={n:(root/n).read_bytes()for n in (*update.FILES['client'],mp.name)};replace=update.replace;failed=False
  def fail(path,raw):
   nonlocal failed
   if path.name=='community_game.py'and not failed:failed=True;raise OSError('interrupted')
   replace(path,raw)
  with patch.object(update,'replace',fail):
   with self.assertRaises(OSError):update.apply(root,payload,'client')
  self.assertEqual({n:(root/n).read_bytes()for n in before},before)

if __name__=='__main__':unittest.main()
