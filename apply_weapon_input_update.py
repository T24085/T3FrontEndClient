"""Update only the community client's weapon input runtime, with a local backup."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,shutil
HERE=Path(__file__).resolve().parent
REVISION='Weapon-Input-Recovery-20261104-r1'
BEGIN='-- BEGIN_WEAPON_INPUT_RECOVERY_V1'
END='-- END_WEAPON_INPUT_RECOVERY_V1'
ANCHOR='local function observe_markers(pc,ps,gs)'
def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return(json.dumps(value,indent=2)+'\n').encode('utf-8')
def compose(source,module):
 assert len(module.encode())<=32768 and 'return function(env)'in module
 assert 'WEAPON_PROBE_'not in source,'Diagnostic clients cannot be updated for release.'
 block=BEGIN+'|sha256='+digest(module.encode())+'\nlocal weaponInputFactory=(function()\n'+module+'\nend)()\nlocal weaponInput=weaponInputFactory({valid=valid,scope=scope,signature=signature,report=report})\n'+END+'\n'
 if BEGIN in source:
  assert source.count(BEGIN)==1 and source.count(END)==1,'Ambiguous prior weapon input update.'
  start=source.index(BEGIN);finish=source.index(END)+len(END)+1
  assert source[start:finish]==block,'A different weapon input revision is already installed.'
  assert source.count(ANCHOR+'\n weaponInput(pc,ps)')==1
  return source
 assert source.count(ANCHOR)==1,'Client input entry point changed.'
 assert 'local function signature('in source and 'local function scope('in source
 return source.replace(ANCHOR,block+ANCHOR+'\n weaponInput(pc,ps)',1)
def apply(root):
 root=Path(root).resolve(strict=True)
 manifestPath=root/'package-manifest.json';luaPath=root/'lua/client.lua'
 before=manifestPath.read_bytes();manifest=json.loads(before)
 matches=[row for row in manifest['files']if row['path']=='lua/client.lua'];assert len(matches)==1
 row=matches[0];original=luaPath.read_bytes()
 assert len(original)==row['bytes']and digest(original)==row['sha256'],'Installed client Lua differs from its inventory.'
 assert all('lua/client.lua'not in paths for paths in manifest.get('map_runtime',{}).values()),'This client declares weapon Lua as map content; a paired update is required.'
 modulePath=HERE/'weapon_input.lua'
 if not modulePath.exists():modulePath=HERE/'runtime-fixes/weapon_input.lua'
 if not modulePath.exists():modulePath=HERE/'weapon_input_candidate.lua'
 module=modulePath.read_text(encoding='utf-8')
 result=compose(original.decode('utf-8'),module).encode('utf-8')
 if result==original:return {'status':'already_installed','root':str(root),'revision':REVISION}
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=root.parent/(root.name+'.before-weapon-input-'+stamp);backup.mkdir(exist_ok=False)
 (backup/'client.lua').write_bytes(original);(backup/'package-manifest.json').write_bytes(before)
 inventoryBefore={r['path']:(r['bytes'],r['sha256'])for r in manifest['files']}
 row.update(bytes=len(result),sha256=digest(result))
 manifest['weapon_input_revision']=REVISION
 inventoryAfter={r['path']:(r['bytes'],r['sha256'])for r in manifest['files']}
 assert {k:v for k,v in inventoryBefore.items()if k!='lua/client.lua'}=={k:v for k,v in inventoryAfter.items()if k!='lua/client.lua'}
 assert manifestPath.read_bytes()==before and luaPath.read_bytes()==original,'Client changed while preparing the update.'
 temp=luaPath.with_suffix('.weapon-input.new');assert not temp.exists();temp.write_bytes(result)
 try:
  os.replace(temp,luaPath)
  tempManifest=manifestPath.with_suffix('.weapon-input.new');tempManifest.write_bytes(encoded(manifest));os.replace(tempManifest,manifestPath)
 except BaseException:
  rollback=luaPath.with_suffix('.weapon-input.rollback');rollback.write_bytes(original);os.replace(rollback,luaPath)
  raise
 proof={'status':'installed','root':str(root),'revision':REVISION,'backup':str(backup),'changed_payload_files':['lua/client.lua'],'before_manifest_sha256':digest(before),'after_manifest_sha256':digest(manifestPath.read_bytes()),'module_sha256':digest(module.encode()),'maps':manifest['community_maps'],'map_inventories_unchanged':True,'other_inventory_entries_unchanged':True,'native_server_cancellation_protocol':True,'requires_server_restart':False}
 (backup/'update-result.json').write_bytes(encoded(proof))
 return proof
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path);args=parser.parse_args()
 print(json.dumps(apply(args.root),indent=2),flush=True)
