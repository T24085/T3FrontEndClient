"""One-use, identity-guarded client file preparation; never starts the game.

Preparation owns fresh session metadata and an exclusive game directory. Only
immutable bulk assets may be linked. Executable/runtime bytes are private. A joining child must
receive the descriptor digest from the successful owned preparer, verify fresh
input and output identities, and win an exclusive claim before using the files.
Profiles and match destinations deliberately do not exist during preparation.
"""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import time
import uuid

from bulk_asset_cache import BulkStageCache
from verified_file_cache import MAX_PACKAGE_FILES, identity

CONTRACT='prepared-client-v1'
MAX_DESCRIPTOR_BYTES=16*1024*1024
MAX_PREPARED_IDENTITIES=2*MAX_PACKAGE_FILES+1
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
 if not 1<=len(names)<=MAX_PREPARED_IDENTITIES or len(set(name.casefold()for name in names))!=len(names):
  raise ValueError('Prepared inventory is empty, duplicate or oversized.')
 return {name:list(identity(_member(root,name)))for name in names}

def _check_stamps(root,records):
 if not isinstance(records,dict)or not 1<=len(records)<=MAX_PREPARED_IDENTITIES:raise ValueError('Prepared identity inventory is invalid.')
 for name,expected in records.items():
  if not isinstance(expected,list)or len(expected)!=5 or list(identity(_member(root,name)))!=expected:
   raise ValueError('Prepared files changed; prepare the client again: '+name)

def _write(path,record):
 raw=(json.dumps(record,indent=2)+'\n').encode('utf-8')
 if len(raw)>MAX_DESCRIPTOR_BYTES:raise ValueError('Prepared descriptor exceeded its bound.')
 with path.open('xb')as output:output.write(raw)
 return hashlib.sha256(raw).hexdigest()

def _copy_private(source,destination):
 """Copy mutable runtime bytes exclusively into a fresh private file."""
 with destination.open('xb')as output,source.open('rb')as stream:shutil.copyfileobj(stream,output,1024*1024)

def _plain_directory(path):
    path.mkdir(exist_ok=True)
    if path.resolve(strict=True) != path or path.is_symlink() or path.is_junction() or not path.is_dir():
        raise ValueError('Stable client directory escaped the workspace.')


def _read_json(path, limit=MAX_DESCRIPTOR_BYTES):
    if path.resolve(strict=True) != path or path.is_symlink() or not path.is_file():
        raise ValueError('Unexpected stable client record location.')
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Stable client record exceeds its bound.')
    return json.loads(raw)


def _installation_key(package):
    return hashlib.sha256(os.path.normcase(str(package)).encode('utf-8')).hexdigest()[:24]


def stable_lobby_path(workspace, package):
    return Path(workspace) / ('lobby-install-' + _installation_key(package))


def desktop_game_job_name(attempt):
    # A global name lets a later Starter session find the same Job across Windows logons.
    if not re.fullmatch(r'[0-9a-f]{32}', attempt):
        raise ValueError('Unexpected desktop Job attempt.')
    return 'Global\\Tribes3Starter-' + attempt


def _retain_recovery_job(name):
    from owned_native_session import C, EXT, K

    K.GetCurrentProcess.argtypes = []
    K.GetCurrentProcess.restype = C.wintypes.HANDLE
    C.set_last_error(0)
    job = K.CreateJobObjectW(None, name)
    if not job:
        return False
    fresh = C.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    limits = EXT()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (fresh and K.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits))
            and K.AssignProcessToJobObject(job, K.GetCurrentProcess())):
        K.CloseHandle(job)
        return False
    # The wrapper is in this Job. Windows closes its noninheritable handle when
    # the wrapper exits, and terminates any game processes still in the Job.
    return True


def _recovery_job_is_gone(name):
    from owned_native_session import C, K

    K.OpenJobObjectW.argtypes = [C.wintypes.DWORD, C.wintypes.BOOL, C.wintypes.LPCWSTR]
    K.OpenJobObjectW.restype = C.wintypes.HANDLE
    job = K.OpenJobObjectW(0x0004, False, name)  # JOB_OBJECT_QUERY
    if not job:
        return C.get_last_error() == 2  # ERROR_FILE_NOT_FOUND
    K.CloseHandle(job)
    return False


class StableGame:
    """A game tree whose lock is held through native Job cleanup."""

    def __init__(self, root, source, workspace):
        self.package = root
        self.workspace = workspace
        self.slot = workspace / ('game-install-' + _installation_key(root))
        self.lobby = stable_lobby_path(workspace, root)
        self.game = self.slot / 'game'
        self.ready = self.slot / 'ready.json'
        self.native = self.slot / 'native.json'
        if any(path == boundary or path in boundary.parents or boundary in path.parents
               for path in (self.slot, self.lobby) for boundary in (root, source)):
            raise ValueError('Stable client files must be outside the Starter package and original game.')

    def check_idle(self):
        if not os.path.lexists(self.native):
            return
        try:
            pending = _read_json(self.native, 65536)
            run = _staged_session_path(self.workspace, pending['run'], self.package)
            if pending['argv'][0] != str(self.game/EXECUTABLE):
                raise ValueError('Unexpected pending game path.')
            # Session metadata can be missing while the stable reservation survives.
            # The desktop Job keeps independent ownership evidence for that case.
            inner_done = False
            if os.path.lexists(run):
                staged_session(self.workspace, run, package=self.package)
                inner_done = self._native_job_empty(run, pending['argv'])
            if inner_done or self._desktop_job_empty(pending.get('desktop')):
                self.native.unlink()
                return
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
        raise ValueError('The previous game Job has no confirmed cleanup. The stable game files are still reserved.')

    def _native_job_empty(self, run, argv):
        try:
            receipt = _read_json(run/'execution/execution.json', 65536)
            return receipt['argv'] == argv and Path(receipt['cwd']) == self.game and _terminal_job_empty(receipt)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _desktop_job_name(self, path):
        attempt = path.parent.parent
        control = attempt.parent
        if (path.name != 'execution.json' or path.parent.name != 'owner'
                or control.parent != self.workspace or control.name not in ('desktop-control','direct-desktop-control')):
            raise ValueError('Unexpected desktop Job location.')
        return desktop_game_job_name(attempt.name)

    def _desktop_job(self, path):
        self._desktop_job_name(path)
        receipt = _read_json(path,65536)
        argv = receipt['argv']
        if (Path(receipt['cwd']) != self.package or Path(argv[0]) != self.package/'python/python.exe'
                or Path(argv[3]) != self.package/'client.py' or '--workspace' not in argv
                or Path(argv[argv.index('--workspace')+1]) != self.workspace
                or receipt.get('assigned_suspended') is not True):
            raise ValueError('Unexpected desktop Job binding.')
        return receipt

    def _desktop_job_empty(self, desktop):
        if desktop is None:
            return False
        path = Path(desktop['path'])
        name = self._desktop_job_name(path)
        try:
            receipt = self._desktop_job(path)
            if receipt['pid'] == desktop['pid'] and receipt['argv'] == desktop['argv'] and _terminal_job_empty(receipt):
                return True
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
        if os.name == 'nt' and desktop.get('job_name') == name:
            return _recovery_job_is_gone(name)
        return False

    def starting(self, run, argv, desktop_job=None):
        staged_session(self.workspace, run, package=self.package)
        if os.path.lexists(self.native) or argv[0] != str(self.game/EXECUTABLE):
            raise ValueError('Native game path differs from the reserved installation.')
        pending = {'run': str(run), 'argv': argv}
        if desktop_job is not None:
            receipt = self._desktop_job(Path(desktop_job))
            if receipt['pid'] != os.getpid() or receipt['status'] != 'running':
                raise ValueError('The desktop Job does not own this client process.')
            pending['desktop'] = {'path':str(desktop_job), 'pid':receipt['pid'], 'argv':receipt['argv']}
            name = self._desktop_job_name(Path(desktop_job))
            if os.name == 'nt' and _retain_recovery_job(name):
                pending['desktop']['job_name'] = name
        _replace_file(self.native, lambda temporary: _write(temporary, pending))


def _terminal_job_empty(receipt):
    return (receipt.get('assigned_suspended') is True and empty_client_job(receipt)
            and receipt['status'] in ('terminal','cancelled_by_owner_request','deadline_terminated','supervisor_error'))


def stable_session_executable(root, run, execution):
    """Resolve the executable for consumers of a running client's Job receipt."""
    root = Path(root).resolve(strict=True)
    run = staged_session(run.parent, run, package=root)
    session = _read_json(run/'session.json', 65536)
    stable = StableGame(root, Path(session['source']).resolve(strict=True), run.parent)
    executable = stable.game/EXECUTABLE
    argv = execution['argv']
    pending = _read_json(stable.native, 65536)
    if (not argv or argv[0] != str(executable) or session['argv'] != argv or Path(execution['cwd']) != stable.game
            or pending['run'] != str(run) or pending['argv'] != argv):
        raise ValueError('The running session does not own this stable executable.')
    return _member(stable.game, EXECUTABLE.as_posix())


@contextmanager
def lock_stable_game(root, source, workspace):
    root, source, workspace = (Path(value).resolve(strict=True) for value in (root, source, workspace))
    stable = StableGame(root, source, workspace)
    _plain_directory(stable.slot)
    lock = stable.slot/'game.lock'
    if os.path.lexists(lock):
        _member(stable.slot, 'game.lock')
    with lock.open('a+b') as handle:
        if lock.stat().st_size == 0:
            handle.write(b'\0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError('This Starter installation is already preparing or running the game.') from exc
        stable.check_idle()
        _plain_directory(stable.game)
        yield stable


def _game_files(game):
    if game.resolve(strict=True) != game or game.is_symlink() or game.is_junction() or not game.is_dir():
        raise ValueError('Unexpected staged game directory.')
    result = {}
    for directory, directories, files in os.walk(game):
        for name in (*directories, *files):
            path = Path(directory)/name
            if path.is_symlink() or path.is_junction() or path.resolve(strict=True) != path:
                raise ValueError('Unexpected link in the staged game: '+name)
        for name in files:
            path = Path(directory)/name
            if not path.is_file():
                raise ValueError('Unexpected item in the staged game: '+name)
            result[path.relative_to(game).as_posix()] = path
    return result


def _replace_file(target, populate):
    temporary = target.with_name('.staging-'+uuid.uuid4().hex)
    try:
        populate(temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _patched_digest(source, original_sha, patches):
    original = hashlib.sha256()
    patched = hashlib.sha256()
    with source.open('rb') as stream:
        for offset, before in sorted(patches):
            remaining = offset-stream.tell()
            if remaining < 0:
                raise ValueError('Executable patch ranges overlap.')
            while remaining:
                block = stream.read(min(remaining,1024*1024))
                if not block:
                    raise ValueError('Executable patch is outside the original file.')
                original.update(block)
                patched.update(block)
                remaining -= len(block)
            before = bytes.fromhex(before)
            if stream.read(len(before)) != before:
                raise ValueError('Unsupported prepared executable at '+hex(offset))
            original.update(before)
            patched.update(b'\x90'*len(before))
        for block in iter(lambda: stream.read(1024*1024), b''):
            original.update(block)
            patched.update(block)
    if original.hexdigest() != original_sha:
        raise ValueError('Original executable differs from the verified inventory.')
    return patched.hexdigest()


def _stage_executable(source, target, original_sha, patches, stable):
    expected = _patched_digest(source, original_sha, patches) if stable else None
    if stable and target.is_file() and target.stat().st_nlink == 1 and digest(target) == expected:
        return expected

    def populate(temporary):
        _copy_private(source, temporary)
        if os.path.samefile(temporary, source) or digest(temporary) != original_sha:
            raise ValueError('Private prepared executable verification failed.')
        with temporary.open('r+b') as output:
            for offset, before in patches:
                before = bytes.fromhex(before)
                output.seek(offset)
                if output.read(len(before)) != before:
                    raise ValueError('Unsupported prepared executable at '+hex(offset))
                output.seek(offset)
                output.write(b'\x90'*len(before))
        if expected is not None and digest(temporary) != expected:
            raise ValueError('Patched executable verification failed.')

    if stable:
        _replace_file(target, populate)
    else:
        populate(target)
    return expected if stable else digest(target)


def stage(root,source,workspace,package,original,original_identities,verification,*,catalog,
          emit=print,cache_factory=BulkStageCache,patches=PATCHES,map_overlay=None,custom_maps=None,
          objectives_downloaded=False,stable=None):
 """Stage the verified inventory while the caller owns any stable slot."""
 root=Path(root).resolve(strict=True);source=Path(source).resolve(strict=True);workspace=Path(workspace).resolve(strict=True)
 if workspace==source or source in workspace.parents:raise ValueError('Client workspace must be outside the original game.')
 package_path=root/'package-manifest.json'
 package_sha=digest(package_path)
 selected_inputs = [entry['path'] for entry in package['files']
                    if map_overlay is None or not entry['path'].startswith('content/')]
 if map_overlay is not None:
  selected_inputs.extend(bundled for _, bundled, _ in map_overlay if bundled is not None)
 package_ids=_stamps(root,list(dict.fromkeys([*selected_inputs,'package-manifest.json'])))
 source_ids={entry['path']:list(original_identities[entry['path']])for entry in original['files']}
 _check_stamps(source,source_ids)
 prior={}
 if stable:
  stable.check_idle()
  run,game=stable.lobby,stable.game
  existing=_game_files(game)
  if os.path.lexists(stable.ready):
   prior=_read_json(stable.ready).get('bulk',{})
   stable.ready.unlink()  # Any partial update invalidates every previous descriptor.
  if os.path.lexists(run):
   shutil.rmtree(staged_session(workspace,run,package=root))
  run.mkdir()
 else:
  run=workspace/('client-'+uuid.uuid4().hex[:12]);run.mkdir()
  game=run/'game'
  game.mkdir()
 emit('Session: '+str(run))
 cache=cache_factory(workspace/'asset-cache')
 jobs=[]
 runtimes=[]
 for item in original['files']:
  rel=_relative(item['path']);src=_member(source,item['path']);dst=game/rel
  if list(identity(src))!=source_ids[item['path']]:raise ValueError('Original changed during client preparation.')
  dst.parent.mkdir(parents=True,exist_ok=True)
  if rel!=EXECUTABLE:jobs.append((src,dst,item['sha256'],item['bytes'],source_ids[item['path']]))
 for item in package['files']:
  name=item['path']
  if name.startswith('runtime/'):
   runtimes.append((_member(root,name),game/REL/_relative(name[len('runtime/'):]),item['sha256']))
  elif name.startswith('content/') and map_overlay is None:
   jobs.append((_member(root,name),game/'Topaz/Content'/_relative(name[len('content/'):]),item['sha256'],item['bytes'],None))
 map_objectives=[]
 if map_overlay is not None:
  for item,bundled,download in map_overlay:
   name=item['path']
   src=_member(root,bundled) if bundled is not None else _member(workspace,download.relative_to(workspace).as_posix())
   if name.startswith('lua/'):
    if stable:
     from map_sync import cache_path
     if bundled is not None or src!=cache_path(workspace,item['sha256']+'.asset'):
      raise ValueError('Prepared map objectives must use the shared download cache: '+name)
    else:
     target=run/'downloaded-objectives'/_relative(name)
     target.parent.mkdir(parents=True,exist_ok=True)
     _copy_private(src,target)
     if target.stat().st_size!=item['bytes'] or digest(target)!=item['sha256']:
      raise ValueError('Prepared map objectives differ: '+name)
    map_objectives.append(item)
    continue
   jobs.append((src,game/'Topaz/Content'/_relative(name[len('content/'):]),item['sha256'],item['bytes'],None))
 exe=game/EXECUTABLE
 required=[exe,*[job[1] for job in jobs],*[job[1] for job in runtimes]]
 wanted={os.path.normcase(str(path)) for path in required}
 if len(required)!=len(wanted):raise ValueError('Game preparation inventories overlap.')
 if stable:
  # Remove only unexpected files in the owned game tree, including prior per-run Lua.
  for path in existing.values():
   if os.path.normcase(str(path)) not in wanted:path.unlink()
 exe_sha=_stage_executable(_member(source,EXECUTABLE.as_posix()),exe,original['executable_sha256'],patches,stable)
 for src,dst,expected in runtimes:
  dst.parent.mkdir(parents=True,exist_ok=True)
  if stable and dst.is_file() and dst.stat().st_nlink==1 and digest(dst)==expected:continue
  def populate(path):
   _copy_private(src,path)
   if digest(path)!=expected:raise ValueError('Prepared runtime copy differs: '+str(dst))
  if stable:_replace_file(dst,populate)
  else:populate(dst)
 def stage_bulk(job):
  src,dst,expected,size,source_identity=job
  name=dst.relative_to(game).as_posix()
  if stable and dst.is_file() and prior.get(name)==[expected,list(identity(dst))]:return
  def populate(path):
   cache.stage(src,path,expected_sha256=expected,expected_bytes=size,expected_source_identity=source_identity)
  if stable:
   dst.parent.mkdir(parents=True,exist_ok=True)
   _replace_file(dst,populate)
  else:populate(dst)
 # Bound metadata I/O to four workers. All work finishes (including on an
 # error) before the original input/output guards can publish a descriptor.
 emit('CLIENT_PREPARATION_PROGRESS|0/'+str(len(jobs)))
 with ThreadPoolExecutor(max_workers=4,thread_name_prefix='client-file-stage')as pool:
  for done,_ in enumerate(pool.map(stage_bulk,jobs),1):
   if done%128==0 or done==len(jobs):emit('CLIENT_PREPARATION_PROGRESS|'+str(done)+'/'+str(len(jobs)))
 _check_stamps(root,package_ids);_check_stamps(source,source_ids)
 if digest(package_path)!=package_sha:raise ValueError('Package manifest changed during client preparation.')
 output_names=sorted(_game_files(game))
 if {os.path.normcase(str(game/name)) for name in output_names}!=wanted:
  raise ValueError('Prepared game file inventory changed.')
 outputs=_stamps(game,output_names)
 record={'format':1,'contract':CONTRACT,'created_at':time.time(),'root':str(root),'source':str(source),'workspace':str(workspace),
         'run':str(run),'package_manifest_sha256':package_sha,'package_inputs':package_ids,'source_inputs':source_ids,
         'game_outputs':outputs,'catalog':catalog,'verification':verification,'private_executable_sha256':exe_sha,
         'bulk_stage':cache.snapshot(),'native_started':False,'profile_created':False}
 if custom_maps:record['custom_maps']=custom_maps
 if objectives_downloaded:record['map_objectives']=map_objectives
 if stable:
  record['stable_game']=str(game)
  record['generation']=uuid.uuid4().hex
  if objectives_downloaded:record['map_objective_cache']=True
 path=run/'prepared.json'
 _replace_file(path,lambda temp:_write(temp,record))
 sha=digest(path)
 if stable:
  bulk={dst.relative_to(game).as_posix():[expected,outputs[dst.relative_to(game).as_posix()]]for _,dst,expected,_,_ in jobs}
  _replace_file(stable.ready,lambda temp:_write(temp,{'run':str(run),'bulk':bulk,'descriptor_sha256':sha}))
 emit('BULK_STAGE_SUMMARY|'+json.dumps(cache.snapshot(),separators=(',',':')))
 result={'path':str(path),'sha256':sha}
 emit('CLIENT_PREPARED|'+json.dumps(result,separators=(',',':')))
 return result


def _staged_session_path(workspace, path, package):
    run = Path(path)
    legacy = re.fullmatch(r'client-[0-9a-f]{12}', run.name)
    lobby = package is not None and run == stable_lobby_path(workspace, package)
    if run.parent != workspace or not (legacy or lobby):
        raise ValueError('Unexpected staged client session.')
    return run


def staged_session(workspace, path, *, package=None):
    """Accept only an immediate, real client session directory."""
    workspace = Path(workspace).resolve(strict=True)
    run = _staged_session_path(workspace, path, package)
    if run.is_symlink() or run.is_junction() or run.resolve(strict=True) != run or not run.is_dir():
        raise ValueError('Unexpected staged client session.')
    return run


def remove_staged_game(workspace, run):
    """Reclaim the owned payload after callers confirm that it is inactive."""
    run = staged_session(workspace, run)
    game = run / 'game'
    if game.is_symlink() or game.is_junction():
        raise ValueError('The staged game directory is a link.')
    deadline = time.monotonic() + 5
    while game.exists():
        if game.resolve(strict=True) != game or not game.is_dir():
            raise ValueError('The staged game escaped its session directory.')
        try:
            shutil.rmtree(game)
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            # Never change attributes on files that can be hardlinked to Steam.
            time.sleep(.25)


def logged_stage(lines):
    """Return the one explicit run announced by an owned launch or preparer."""
    runs = {line[len('Session: '):] for line in lines if line.startswith('Session: ')}
    if len(runs) > 1:
        raise ValueError('The client Job reported more than one session.')
    return Path(runs.pop()) if runs else None


def empty_client_job(result):
    active = result.get('job_active_processes_after_cleanup', result.get('job_active_processes_at_parent_exit'))
    return type(active) is int and active == 0


def consume(root,source,workspace,descriptor,expected_sha,*,expected_map=None,expected_content_hash=None,clock=time.time,stable=None):
 """Freshly validate a completed stage and claim it once before profile/native use."""
 root=Path(root).resolve(strict=True);source=Path(source).resolve(strict=True);workspace=Path(workspace).resolve(strict=True)
 path=Path(descriptor).absolute()
 if path.name!='prepared.json':
  raise ValueError('Unexpected prepared client descriptor path.')
 staged_session(workspace,path.parent,package=root)
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
 if 'stable_game' in record:
  ready=_read_json(stable.ready) if stable is not None and stable.ready.is_file() else {}
  if (stable is None or record['stable_game']!=str(stable.game) or ready.get('run')!=str(path.parent)
      or (path.parent==stable.lobby and ready.get('descriptor_sha256')!=expected_sha)):
   raise ValueError('Prepared stable game was replaced; prepare the client again.')
  game=stable.game
 else:game=path.parent/'game'
 _check_stamps(game,record['game_outputs'])
 actual=set(_game_files(game))
 if actual!=set(record['game_outputs']):raise ValueError('Prepared game file inventory changed.')
 if expected_map is not None and record['catalog'].get(expected_map)!=expected_content_hash:
  raise ValueError('Your map files do not match this match. Update the community client.')
 # Winning the exclusive file is the capability transfer. Any failed join after
 # this point leaves the stage spent; a future join creates a new preparation.
 _write(path.parent/'claimed.json',{'descriptor_sha256':expected_sha,'claim':uuid.uuid4().hex,'claimed_at':clock()})
 return record
