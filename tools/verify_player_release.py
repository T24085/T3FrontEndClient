"""Stream-verify a complete player ZIP and its recorded server map catalog."""
import argparse,ast,hashlib,json,re,sys,zipfile
from pathlib import Path,PurePosixPath
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from map_sync_contract import map_catalog

def safe_name(name):
 p=PurePosixPath(name)
 if not name or p.is_absolute()or p.as_posix()!=name or '..'in p.parts or ':'in name or '\\'in name:raise ValueError('Unsafe member: '+name)
 return p

def verify(archive,server_catalog,output):
 archive=Path(archive);before=archive.stat();output=Path(output);output.mkdir(parents=True,exist_ok=True)
 if before.st_size>=2*1024**3:raise ValueError('Release asset must be below2GiB')
 server=json.loads(Path(server_catalog).read_bytes())
 with zipfile.ZipFile(archive)as z:
  names=[i.filename for i in z.infolist()if not i.is_dir()]
  if len(names)!=len({n.casefold()for n in names}):raise ValueError('Duplicate ZIP members')
  candidates=[n for n in names if n.endswith('/package-manifest.json')and n.count('/')==1]
  if len(candidates)!=1:raise ValueError('One complete top-level client required')
  root=candidates[0].split('/')[0]+'/';manifest=json.loads(z.read(candidates[0]));rows=manifest['files']
  if not 1<=len(rows)<=10000:raise ValueError('Inventory bounds exceeded')
  expected={};total=0
  for row in rows:
   name=row['path'];p=safe_name(name)
   if name.casefold()in expected:raise ValueError('Duplicate inventory path')
   expected[name.casefold()]=name
   if type(row['bytes'])is not int or not 0<=row['bytes']<=256*1024**2 or not re.fullmatch('[0-9a-f]{64}',row['sha256']):raise ValueError('Invalid size or hash')
   total+=row['bytes']
   if p.suffix.lower()in('.key','.pem','.p12','.pfx','.pak','.sig','.dmp')or p.name.lower()in('tribesrivals.exe','tailscale-api-token.txt','server-access-operator.json','server-access-state.json')or any(x.lower()in('profile','logs','local-settings')for x in p.parts):raise ValueError('Private/original-game member: '+name)
   if p.suffix.lower()=='.exe'and name not in('python/python.exe','python/pythonw.exe'):raise ValueError('Unexpected executable: '+name)
  if total>8*1024**3:raise ValueError('Expanded archive bounds exceeded')
  required={'client.py','community_starter.pyw','Start Community Starter.vbs','python/pythonw.exe','lua/client.lua','README-FIRST.txt','RELEASE-INFO.json','base-game-manifest.json'}
  if not required.issubset(set(expected.values())):raise ValueError('Complete player launcher/runtime is missing')
  if set(names)!={root+n for n in expected.values()}|{candidates[0]}:raise ValueError('ZIP differs from declared inventory')
  for n in names:safe_name(n)
  catalog=map_catalog(manifest)
  if catalog!=server['verified_map_catalog']:raise ValueError('Client map fingerprints do not match the current server')
  secret=re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|tskey-api-[A-Za-z0-9_-]{20,}')
  for i,row in enumerate(rows,1):
   name=row['path'];info=z.getinfo(root+name)
   if info.file_size!=row['bytes']:raise ValueError('ZIP length mismatch: '+name)
   h=hashlib.sha256();parts=[];text=Path(name).suffix in('.py','.pyw','.lua','.json','.txt','.ini','.vbs','.bat')
   with z.open(info)as f:
    while chunk:=f.read(4*1024*1024):
     h.update(chunk)
     if text:parts.append(chunk)
   if h.hexdigest()!=row['sha256']:raise ValueError('SHA256 mismatch: '+name)
   if text:
    raw=b''.join(parts)
    if secret.search(raw):raise ValueError('Possible credential in '+name)
    if Path(name).suffix in('.py','.pyw'):ast.parse(raw,filename=name)
   if i%1000==0:print(f'Verified {i}/{len(rows)} members',flush=True)
  info=json.loads(z.read(root+'RELEASE-INFO.json'))
  if info['verified_map_catalog']!=catalog:raise ValueError('Embedded release catalog differs')
 after=archive.stat()
 if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Archive changed during verification')
 with archive.open('rb')as f:archive_sha=hashlib.file_digest(f,'sha256').hexdigest()
 report={'archive':archive.name,'archive_bytes':before.st_size,'archive_sha256':archive_sha,'verified_members':len(rows),'expanded_bytes':total,'maps':list(catalog),'verified_map_catalog':catalog,'server_manifest_sha256':server['host_manifest_sha256'],'server_map_match':True,'all_archive_members_sha256_verified':True,'original_game_included':False,'private_keys_included':False,'scope':'Distribution integrity and current server map fingerprint match. Gameplay qualification is recorded separately.','passed':True}
 (output/'VERIFICATION.json').write_text(json.dumps(report,indent=2)+'\n',newline='\n')
 (output/'MAP-CATALOG.json').write_text(json.dumps({'release':info['release'],'maps':catalog},indent=2)+'\n',newline='\n')
 print(json.dumps({'passed':True,'archive_sha256':archive_sha,'maps':len(catalog),'members':len(rows)}),flush=True)
 return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--server-catalog',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();verify(a.archive,a.server_catalog,a.output)
if __name__=='__main__':main()
