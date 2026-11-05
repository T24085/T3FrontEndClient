"""Back up and replace only the three inventoried lobby-recovery modules."""
import argparse,datetime,hashlib,json,os,sys,uuid
from pathlib import Path
FILES={'client':('desktop_launcher.py','community_game.py','community_transport.py'),
       'server':('operator/lobby_controller.py','operator/lobby_http.py','operator/community_transport.py')}
REVISION='lobby-recovery-20261105-r2'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return(json.dumps(value,indent=2)+'\n').encode()
def replace(path,raw):
 temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.update')
 temp.write_bytes(raw);os.replace(temp,path)
def apply(root,payload,kind):
 root,payload=Path(root).resolve(strict=True),Path(payload).resolve(strict=True)
 manifest_name='package-manifest.json'if kind=='client'else'server-package-manifest.json'
 mp=root/manifest_name;original=mp.read_bytes();manifest=json.loads(original);rows={r['path']:r for r in manifest['files']}
 changes={};old={}
 for name in FILES[kind]:
  target=root/name;source=payload/name
  if target.resolve(strict=True)!=target or source.resolve(strict=True)!=source:raise ValueError('Linked update input refused')
  before=target.read_bytes();row=rows[name]
  if len(before)!=row['bytes']or sha(before)!=row['sha256']:raise ValueError('Installed file differs from its inventory: '+name)
  raw=source.read_bytes();compile(raw,name,'exec');changes[name]=raw;old[name]=before
 if all(old[n]==raw for n,raw in changes.items()):return {'status':'already_installed','revision':REVISION}
 before_maps={k:manifest.get(k)for k in ('community_maps','map_runtime','shared_content')}
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup=root.parent/(root.name+'.before-lobby-recovery-'+stamp+'-'+uuid.uuid4().hex[:6]);backup.mkdir(exist_ok=False)
 old[manifest_name]=original
 for name,raw in old.items():
  p=backup/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 for name,raw in changes.items():rows[name].update(bytes=len(raw),sha256=sha(raw))
 manifest['lobby_recovery_revision']=REVISION
 assert before_maps=={k:manifest.get(k)for k in before_maps}
 changes[manifest_name]=encode(manifest)
 if mp.read_bytes()!=original:raise ValueError('Package changed while update was prepared')
 try:
  for name,raw in changes.items():replace(root/name,raw)
 except BaseException:
  for name,raw in old.items():replace(root/name,raw)
  raise
 result={'status':'installed','revision':REVISION,'backup':str(backup),'changed_payload_files':list(FILES[kind]),'maps_unchanged':True,'manifest_sha256':sha((root/manifest_name).read_bytes())}
 (backup/'UPDATE-RESULT.json').write_bytes(encode(result));return result
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--payload',type=Path,required=True);p.add_argument('--kind',choices=FILES,required=True);a=p.parse_args()
 server=None;restart=False
 if a.kind=='server':
  sys.path.insert(0,str(a.root/'operator'));import laptop_server as server
  try:
   _,status=server.owned_run(a.root)
   if any(r.get('phase')in('starting','ready','stopping')for r in status.get('rooms',[])):
    raise RuntimeError('An active match is present. Stop it in the server operator before applying this update.')
   restart=status.get('status')=='ready'
  except FileNotFoundError:pass
  if restart:print(server.stop(a.root),flush=True)
 try:print(json.dumps(apply(a.root,a.payload,a.kind),indent=2),flush=True)
 finally:
  if restart:print(server.start(a.root),flush=True)
if __name__=='__main__':main()
