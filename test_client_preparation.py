"""Real file staging/consumption boundaries without a native game process."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
import io
import sys
from unittest.mock import patch

import client_preparation

from bulk_asset_cache import BulkStageCache
from client_preparation import EXECUTABLE,consume,digest,stage
from verified_file_cache import identity

class ClientPreparationTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='tribes-prepared-client-')
  self.root=Path(self.tmp.name).resolve();self.package=self.root/'package';self.source=self.root/'source';self.workspace=self.root/'workspace'
  for p in (self.package,self.source,self.workspace):p.mkdir()
  for root,name,data in ((self.source,EXECUTABLE,b'EXE!'+bytes.fromhex('e8621439ff')+b'payload'),
                         (self.source,Path('Topaz/Content/Paks/original.pak'),b'original-pak'),
                         (self.package,Path('runtime/ue4ss/runtime.dll'),b'runtime'),
                         (self.package,Path('content/Maps/map.uasset'),b'cooked-map')):
   path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
  self.original=self.inventory(self.source)
  self.original['executable_sha256']=digest(self.source/EXECUTABLE)
  self.package_manifest=self.inventory(self.package)
  (self.package/'package-manifest.json').write_text(json.dumps(self.package_manifest))
  self.catalog={'Stonehenge':'a'*64}
  self.source_ids={x['path']:list(identity(self.source/x['path']))for x in self.original['files']}
 def tearDown(self):self.tmp.cleanup()
 def inventory(self,root):
  return {'files':[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}for p in sorted(root.rglob('*'))if p.is_file()]}
 def prepare(self):
  return stage(self.package,self.source,self.workspace,self.package_manifest,self.original,self.source_ids,'fixture verified bytes',
               catalog=self.catalog,emit=lambda _:None,
               cache_factory=lambda p:BulkStageCache(p,filesystem_loader=lambda _:None,emit=lambda _:None),patches=((4,'e8621439ff'),))
 def claim(self,descriptor,**kwargs):
  return consume(self.package,self.source,self.workspace,descriptor['path'],descriptor['sha256'],
                 expected_map='Stonehenge',expected_content_hash='a'*64,**kwargs)
 def test_real_preparation_is_private_and_has_no_profile_or_native_process(self):
  original=(self.source/EXECUTABLE).read_bytes();descriptor=self.prepare();record=self.claim(descriptor)
  run=Path(record['run']);game=run/'game'
  self.assertEqual((self.source/EXECUTABLE).read_bytes(),original)
  self.assertNotEqual(identity(self.source/EXECUTABLE)[:2],identity(game/EXECUTABLE)[:2])
  self.assertEqual((game/EXECUTABLE).read_bytes()[4:9],b'\x90'*5)
  self.assertEqual((game/'Topaz/Content/Maps/map.uasset').read_bytes(),b'cooked-map')
  self.assertEqual((game/EXECUTABLE.parent/'ue4ss/runtime.dll').read_bytes(),b'runtime')
  self.assertFalse((run/'profile').exists());self.assertFalse(record['native_started']);self.assertFalse(record['profile_created'])
 def test_original_change_invalidates_ready_stage(self):
  descriptor=self.prepare();(self.source/EXECUTABLE).write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'changed'):self.claim(descriptor)
 def test_package_update_invalidates_ready_stage(self):
  descriptor=self.prepare();(self.package/'package-manifest.json').write_text('{}')
  with self.assertRaisesRegex(ValueError,'updated'):self.claim(descriptor)
 def test_staged_runtime_change_invalidates_ready_stage(self):
  descriptor=self.prepare();run=Path(descriptor['path']).parent
  (run/'game'/EXECUTABLE.parent/'ue4ss/runtime.dll').write_bytes(b'tamper')
  with self.assertRaisesRegex(ValueError,'changed'):self.claim(descriptor)
 def test_added_game_file_invalidates_inventory(self):
  descriptor=self.prepare();(Path(descriptor['path']).parent/'game/unexpected.dll').write_bytes(b'extra')
  with self.assertRaisesRegex(ValueError,'inventory'):self.claim(descriptor)
 def test_descriptor_edit_is_not_authorized_by_its_filename(self):
  descriptor=self.prepare();Path(descriptor['path']).write_text('{}')
  with self.assertRaisesRegex(ValueError,'descriptor changed'):self.claim(descriptor)
 def test_selected_map_fingerprint_must_match_at_consume(self):
  descriptor=self.prepare()
  with self.assertRaisesRegex(ValueError,'map files'):
   consume(self.package,self.source,self.workspace,descriptor['path'],descriptor['sha256'],expected_map='Stonehenge',expected_content_hash='b'*64)
  self.claim(descriptor)  # a rejected content check did not spend the stage
 def test_expired_stage_is_not_reused(self):
  descriptor=self.prepare()
  with self.assertRaisesRegex(ValueError,'expired'):self.claim(descriptor,clock=lambda:float('inf'))
 def test_exactly_one_concurrent_consumer_wins(self):
  descriptor=self.prepare();results=[];barrier=threading.Barrier(2)
  def claim():
   barrier.wait()
   try:self.claim(descriptor);results.append('claimed')
   except FileExistsError:results.append('spent')
  threads=[threading.Thread(target=claim)for _ in range(2)]
  for t in threads:t.start()
  for t in threads:t.join(5)
  self.assertEqual(sorted(results),['claimed','spent'])
 def test_another_installation_cannot_consume_stage(self):
  descriptor=self.prepare();other=self.root/'other';other.mkdir()
  with self.assertRaisesRegex(ValueError,'different installation'):
   consume(self.package,other,self.workspace,descriptor['path'],descriptor['sha256'])
 def test_actual_parent_verify_game_identity_contract_can_prepare_and_consume(self):
  parent=Path(__file__).resolve().parent/'lib/client_support.py'
  spec=importlib.util.spec_from_file_location('pinned_client_identity_owner',parent)
  support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
  support.ROOT=self.package
  base=self.package/'base-game-manifest.json';base.write_text(json.dumps(self.original))
  self.package_manifest['files'].append({'path':base.name,'bytes':base.stat().st_size,'sha256':digest(base)})
  (self.package/'package-manifest.json').write_text(json.dumps(self.package_manifest))
  original,observed,verification=support.verify_game(self.source,self.workspace)
  self.assertEqual(observed,{item['path']:list(identity(self.source/item['path']))for item in original['files']})
  self.original,self.source_ids=original,observed
  self.assertTrue(self.claim(self.prepare())['private_executable_sha256'])
 def test_canonical_prepare_only_path_runs_shared_timing_and_never_native(self):
  parent=Path(__file__).resolve().parent/'lib/client_support.py'
  support_spec=importlib.util.spec_from_file_location('actual_cli_support',parent)
  support=importlib.util.module_from_spec(support_spec);support_spec.loader.exec_module(support);support.ROOT=self.package
  replacement=Path(__file__).with_name('client_entry.py')
  spec=importlib.util.spec_from_file_location('actual_prepared_cli',replacement)
  module=importlib.util.module_from_spec(spec)
  with patch.dict(sys.modules,{'client_support':support}):spec.loader.exec_module(module)
  module.verify_package=lambda:self.package_manifest
  module.verify_game=lambda source,workspace,force:(self.original,self.source_ids,'verified fixture')
  module.discover_game=lambda _:self.source
  module.installation_options=lambda game,workspace:(game,self.workspace)
  module.running_image=lambda _:(_ for _ in()).throw(AssertionError('prepare-only reached native launch preflight'))
  original_stage=client_preparation.stage
  def fixture_stage(*args,**kwargs):
   kwargs.update(patches=((4,'e8621439ff'),),cache_factory=lambda p:BulkStageCache(p,filesystem_loader=lambda _:None,emit=lambda _:None))
   return original_stage(*args,**kwargs)
  output=io.StringIO()
  with patch.object(sys,'argv',[str(replacement),'--prepare-only','--game-dir',str(self.source),'--workspace',str(self.workspace)]), \
       patch('map_catalog.verified_catalog',return_value=self.catalog),patch.object(client_preparation,'stage',fixture_stage),redirect_stdout(output):
   module.main()
  rows=output.getvalue().splitlines()
  phases=[json.loads(row[len('STARTUP_PHASE|'):])for row in rows if row.startswith('STARTUP_PHASE|')]
  self.assertTrue(any(row['phase']=='client-preparation'and row['state']=='complete'for row in phases))
  descriptors=[json.loads(row[len('CLIENT_PREPARED|'):])for row in rows if row.startswith('CLIENT_PREPARED|')]
  self.assertEqual(len(descriptors),1);record=self.claim(descriptors[0]);self.assertFalse(record['native_started'])
  self.assertFalse((Path(record['run'])/'profile').exists())

if __name__=='__main__':unittest.main()
