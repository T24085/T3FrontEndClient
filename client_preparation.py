"""One-use, identity-guarded client file preparation; never starts the game.

Preparation owns a fresh isolated directory. Only immutable bulk assets may be
linked. Executable/runtime/configuration bytes are private. A joining child must
receive the descriptor digest from the successful owned preparer, verify fresh
input and output identities, and win an exclusive claim before using the files.
Profiles and match destinations deliberately do not exist during preparation.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import uuid

from bulk_asset_cache import BulkStageCache
from verified_file_cache import identity

CONTRACT='prepared-client-v1'
MAX_DESCRIPTOR_BYTES=4*1024*1024
MAX_AGE_SECONDS=86400
EXECUTABLE=Path('Topaz/Binaries/Win64/TribesRivals.exe')
REL=EXECUTABLE.parent
PATCHES=((0x1a8b909,'e8621439ff'),(0x1a8b933,'e8381439ff'),
         (0x1a8b95d,'e80e1439ff'),(0x1a8b987,'e8e41339ff'))

def digest(path):
 with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def _relative(name):
 rel=PurePosixPath(name)
 if not isinstance(name,str)or not rel.parts or rel.is_absolute()or rel.as_posix()!=name or '..'in rel.parts or ':'in name or '\\'in name:
  raise ValueError('Unsafe prepared file inventory path.')
 return Path(*rel.parts)

def _member(root,name):
 path=root/_relative(name)
 if path.is_symlink()or path.is_junction()or path.resolve(strict=True)!=path or root not in path.parents:
  raise ValueError('Prepared input or output escaped its selected root.')
 return path

def _stamps(root,names):
 if not 1<=len(names)<=10000 or len(set(name.casefold()for name in names))!=len(names):
  raise ValueError('Prepared inventory is empty, duplicate or oversized.')
 return {name:list(identity(_member(root,name)))for name in names}

def _check_stamps(root,records):
 if not isinstance(records,dict)or not 1<=len(records)<=10000:raise ValueError('Prepared identity inventory is invalid.')
 for name,expected in records.items():
  if not isinstance(expected,list)or len(expected)!=5 or list(identity(_member(root,name)))!=expected:
   raise ValueError('Prepared files changed; prepare the client again: '+name)

def _write(path,record):
 raw=(json.dumps(record,indent=2)+'\n').encode('utf-8')
 if len(raw)>MAX_DESCRIPTOR_BYTES:raise ValueError('Prepared descriptor exceeded its bound.')
 with path.open('xb')as output:output.write(raw)
 return hashlib.sha256(raw).hexdigest()

def stage(root,source,workspace,package,original,original_identities,verification,*,catalog,
          emit=print,cache_factory=BulkStageCache,patches=PATCHES):
 """Stage exactly the verified inventories into a fresh private directory."""
 root=Path(root).resolve(strict=True);source=Path(source).resolve(strict=True);workspace=Path(workspace).resolve(strict=True)
 if workspace==source or source in workspace.parents:raise ValueError('Client workspace must be outside the original game.')
 package_path=root/'package-manifest.json'
 package_sha=digest(package_path)
 package_ids=_stamps(root,[entry['path']for entry in package['files']]+['package-manifest.json'])
 source_ids={entry['path']:list(original_identities[entry['path']])for entry in original['files']}
 _check_stamps(source,source_ids)
 run=workspace/('client-'+uuid.uuid4().hex[:12]);run.mkdir(exist_ok=False)
 game=run/'game';game.mkdir()
 emit('Session: '+str(run))
 cache=cache_factory(workspace/'asset-cache')
 for item in original['files']:
  rel=_relative(item['path']);src=_member(source,item['path']);dst=game/rel
  if list(identity(src))!=source_ids[item['path']]:raise ValueError('Original changed during client preparation.')
  dst.parent.mkdir(parents=True,exist_ok=True)
  if rel==EXECUTABLE:
   with dst.open('xb')as output,src.open('rb')as stream:shutil.copyfileobj(stream,output,1024*1024)
  else:cache.stage(src,dst,expected_sha256=item['sha256'],expected_bytes=item['bytes'],expected_source_identity=source_ids[item['path']])
 exe=game/EXECUTABLE
 if os.path.samefile(exe,source/EXECUTABLE)or digest(exe)!=original['executable_sha256']:
  raise ValueError('Private prepared executable verification failed.')
 with exe.open('r+b')as output:
  for offset,before in patches:
   output.seek(offset)
   if output.read(len(bytes.fromhex(before)))!=bytes.fromhex(before):raise ValueError('Unsupported prepared executable at '+hex(offset))
  for offset,before in patches:output.seek(offset);output.write(b'\x90'*len(bytes.fromhex(before)))
 for item in package['files']:
  name=item['path']
  if name.startswith('runtime/'):
   src=_member(root,name);dst=game/REL/_relative(name[len('runtime/'):]);dst.parent.mkdir(parents=True,exist_ok=True)
   # Never overwrite a destination which might share original immutable bytes.
   with dst.open('xb')as output,src.open('rb')as stream:shutil.copyfileobj(stream,output,1024*1024)
   if digest(dst)!=item['sha256']:raise ValueError('Prepared runtime copy differs: '+name)
  elif name.startswith('content/'):
   cache.stage(_member(root,name),game/'Topaz/Content'/_relative(name[len('content/'):]),expected_sha256=item['sha256'],expected_bytes=item['bytes'])
 _check_stamps(root,package_ids);_check_stamps(source,source_ids)
 if digest(package_path)!=package_sha:raise ValueError('Package manifest changed during client preparation.')
 output_names=[path.relative_to(game).as_posix()for path in sorted(game.rglob('*'))if path.is_file()]
 outputs=_stamps(game,output_names)
 record={'format':1,'contract':CONTRACT,'created_at':time.time(),'root':str(root),'source':str(source),'workspace':str(workspace),
         'run':str(run),'package_manifest_sha256':package_sha,'package_inputs':package_ids,'source_inputs':source_ids,
         'game_outputs':outputs,'catalog':catalog,'verification':verification,'private_executable_sha256':digest(exe),
         'bulk_stage':cache.snapshot(),'native_started':False,'profile_created':False}
 path=run/'prepared.json';sha=_write(path,record)
 emit('BULK_STAGE_SUMMARY|'+json.dumps(cache.snapshot(),separators=(',',':')))
 result={'path':str(path),'sha256':sha}
 emit('CLIENT_PREPARED|'+json.dumps(result,separators=(',',':')))
 return result

def consume(root,source,workspace,descriptor,expected_sha,*,expected_map=None,expected_content_hash=None,clock=time.time):
 """Freshly validate a completed stage and claim it once before profile/native use."""
 root=Path(root).resolve(strict=True);source=Path(source).resolve(strict=True);workspace=Path(workspace).resolve(strict=True)
 path=Path(descriptor).absolute()
 if path.name!='prepared.json'or path.parent.parent!=workspace or re.fullmatch(r'client-[0-9a-f]{12}',path.parent.name)is None:
  raise ValueError('Unexpected prepared client descriptor path.')
 if path.resolve(strict=True)!=path or path.is_symlink()or path.is_junction():raise ValueError('Prepared client descriptor escaped its owner.')
 before=identity(path)
 with path.open('rb')as stream:raw=stream.read(MAX_DESCRIPTOR_BYTES+1)
 if (not isinstance(expected_sha,str)or re.fullmatch('[0-9a-f]{64}',expected_sha)is None or len(raw)>MAX_DESCRIPTOR_BYTES
     or identity(path)!=before or hashlib.sha256(raw).hexdigest()!=expected_sha):raise ValueError('Prepared descriptor changed after preparation.')
 record=json.loads(raw)
 if not isinstance(record,dict)or record.get('format')!=1 or record.get('contract')!=CONTRACT:raise ValueError('Unknown prepared client contract.')
 if any(record.get(key)!=str(value)for key,value in (('root',root),('source',source),('workspace',workspace),('run',path.parent))):
  raise ValueError('Prepared client belongs to a different installation or package.')
 created=record.get('created_at')
 if type(created)not in(int,float)or not 0<=clock()-created<MAX_AGE_SECONDS:raise ValueError('Prepared client expired; prepare it again.')
 if record.get('native_started')is not False or record.get('profile_created')is not False:raise ValueError('Preparation must not start a native game or profile.')
 package_path=root/'package-manifest.json'
 if digest(package_path)!=record['package_manifest_sha256']:raise ValueError('Client was updated after preparation.')
 _check_stamps(root,record['package_inputs']);_check_stamps(source,record['source_inputs'])
 game=path.parent/'game';_check_stamps(game,record['game_outputs'])
 actual={p.relative_to(game).as_posix()for p in game.rglob('*')if p.is_file()}
 if actual!=set(record['game_outputs']):raise ValueError('Prepared game file inventory changed.')
 if expected_map is not None and record['catalog'].get(expected_map)!=expected_content_hash:
  raise ValueError('Your map files do not match this match. Update the community client.')
 # Winning the exclusive file is the capability transfer. Any failed join after
 # this point leaves the stage spent; a future join creates a new preparation.
 _write(path.parent/'claimed.json',{'descriptor_sha256':expected_sha,'claim':uuid.uuid4().hex,'claimed_at':clock()})
 return record
