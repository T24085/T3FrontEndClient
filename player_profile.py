"""Per-Windows-user native community preferences, independent of ZIP/workspace.

No profile bytes belong in the client package. Native UserDir owns future config
and SaveGame writes. Only proven clean human community sessions may seed a new
profile; an existing profile always wins and is never reimported automatically.

Canonical baseline: Worldbuilding-20261102-r1/player_profile.py,
SHA256 a21985a96b4f58b05835fc3d9ca4f8365d6fa54a70fff64e31bc91e28c713b9a.
"""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import uuid


class ProfileError(ValueError):
    pass


class ProfileBusy(ProfileError):
    pass


_RETAINED_LEASES = []
INI_LIMIT = 1024 * 1024
MIGRATE_FILES = ('GameUserSettings.ini', 'Input.ini', 'EnhancedInput.ini', 'Scalability.ini')
BOOTSTRAP_SECTION = '/Script/EngineSettings.GameMapsSettings'


def user_profile_root():
    """Use the OS known folder, without packaged-Python LOCALAPPDATA redirection."""
    if os.name != 'nt':
        return Path.home()/'.local/share/Tribes3CommunityStarter/player-settings'
    class GUID(ctypes.Structure):
        _fields_ = [('Data1', ctypes.c_uint32), ('Data2', ctypes.c_uint16),
                    ('Data3', ctypes.c_uint16), ('Data4', ctypes.c_ubyte * 8)]
    # FOLDERID_LocalAppData; KF_FLAG_NO_PACKAGE_REDIRECTION.
    folder = GUID(0xf1b32785, 0x6fba, 0x4fcf,
                  (ctypes.c_ubyte * 8)(0x9d, 0x55, 0x7b, 0x8e, 0x7f, 0x15, 0x70, 0x91))
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = (ctypes.POINTER(GUID), ctypes.c_uint32,
                                         ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p))
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    value = ctypes.c_wchar_p()
    result = shell.SHGetKnownFolderPath(ctypes.byref(folder), 0x10000, None, ctypes.byref(value))
    if result != 0:
        raise ProfileError('Windows could not locate durable player settings: ' + hex(result & 0xffffffff))
    try:
        return Path(value.value)/'Tribes3CommunityStarter/player-settings'
    finally:
        free = ctypes.WinDLL('ole32').CoTaskMemFree
        free.argtypes = (ctypes.c_void_p,)
        free.restype = None
        free(ctypes.cast(value, ctypes.c_void_p))


def _identity(path):
    st = path.stat()
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _plain(path):
    if path.is_symlink() or path.is_junction():
        raise ProfileError('Linked player-profile input is not supported: ' + str(path))


def _child(root, relative):
    """Do not let a linked Saved/Config parent redirect profile writes."""
    root = Path(root)
    _plain(root)
    current = root
    for part in Path(relative).parts:
        if part in ('.', '..') or ':' in part:
            raise ProfileError('Unsafe player-profile path.')
        current = current/part
        if os.path.lexists(current): _plain(current)
    if root.resolve() not in current.resolve().parents:
        raise ProfileError('Player-profile path escaped its owner.')
    return current


def _read(path, limit):
    _plain(path)
    before = _identity(path)
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit or _identity(path) != before:
        raise ProfileError('Player-profile input changed or exceeded its bound: ' + str(path))
    return raw


def _ini(raw):
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        text = raw.decode(encoding)
    except UnicodeError as exc:
        raise ProfileError('Player settings have unknown text encoding.') from exc
    if '\0' in text:
        raise ProfileError('Player settings contain unexpected NUL text.')
    section = None
    rows = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        match = re.fullmatch(r'\[([^\]\r\n]+)\]\s*(?:;.*)?', stripped)
        if match:
            section = match[1]
            rows.append((line, section, None))
        elif not stripped or stripped.startswith((';', '#')):
            rows.append((line, section, None))
        elif '=' in line and section is not None:
            key = line.split('=', 1)[0].strip()
            if not key:
                raise ProfileError('Player settings contain an empty INI key.')
            rows.append((line, section, key))
        else:
            raise ProfileError('Player settings INI structure is unknown; original bytes retained.')
    return text, rows


def _backup(path, root, raw):
    directory = root/'backups'
    directory.mkdir(exist_ok=True)
    _plain(directory)
    target = directory/(path.name+'.'+hashlib.sha256(raw).hexdigest()+'.bak')
    try:
        with target.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        if _read(target, INI_LIMIT) != raw:
            raise ProfileError('Existing profile backup differs; retained: ' + str(target))
    return target


def _atomic(path, raw):
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('xb') as stream:
        stream.write(raw)
    try:
        os.replace(temp, path)
    except BaseException:
        # Keep the exactly named owned temporary if publication failed.
        raise ProfileError('Player-settings update could not be published; retained: '+str(temp))


def _valid_bootstrap_map(map_name):
    if map_name == '/Game/Maps/Active/Drydock/Arena_Drydock_P':
        return True
    from community_maps import BY_ID
    return isinstance(map_name, str) and any(map_name == row.package for row in BY_ID.values())


def update_bootstrap(profile, control, mode, *, map_name='/Game/Maps/Active/Drydock/Arena_Drydock_P'):
    """Preserve all other raw INI lines; change only these three owned keys."""
    if not isinstance(mode, str) or '\n' in mode or '\r' in mode:
        raise ProfileError('Invalid community bootstrap mode.')
    if not _valid_bootstrap_map(map_name):
        raise ProfileError('Invalid community bootstrap map.')
    path = _child(profile, 'Saved/Config/Windows/Engine.ini')
    path.parent.mkdir(parents=True, exist_ok=True)
    _plain(path.parent)
    raw = _read(path, INI_LIMIT) if path.exists() else b''
    try:
        text, rows = _ini(raw)
    except ProfileError:
        _backup(path, control, raw)
        raise
    newline = '\r\n' if '\r\n' in text else '\n'
    owned = {'gamedefaultmap', 'globaldefaultgamemode', 'localmapoptions'}
    inserted = False
    output = []
    values = ('GameDefaultMap='+map_name,
              'GlobalDefaultGameMode='+mode, 'LocalMapOptions=?game='+mode)
    for line, section, key in rows:
        if section is not None and section.casefold() == BOOTSTRAP_SECTION.casefold():
            if key is None and line.strip().startswith('[') and not inserted:
                output.append(line)
                output.extend(value+newline for value in values)
                inserted = True
                continue
            if key is not None and key.lstrip('+-!.').casefold() in owned:
                continue
        output.append(line)
    if not inserted:
        if output and not output[-1].endswith(('\n', '\r')):
            output.append(newline)
        output.append('['+BOOTSTRAP_SECTION+']'+newline)
        output.extend(value+newline for value in values)
    text = ''.join(output)
    if raw.startswith(b'\xff\xfe'): updated = b'\xff\xfe'+text.encode('utf-16-le')
    elif raw.startswith(b'\xfe\xff'): updated = b'\xfe\xff'+text.encode('utf-16-be')
    elif raw.startswith(b'\xef\xbb\xbf'): updated = b'\xef\xbb\xbf'+text.encode('utf-8')
    else: updated = text.encode('utf-8')
    if updated != raw:
        if path.exists():
            _backup(path, control, raw)
            if _read(path, INI_LIMIT) != raw:
                raise ProfileError('Engine preferences changed during bootstrap merge; original retained.')
        _atomic(path, updated)


def _json(path, limit):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ProfileError('Duplicate owned JSON key: '+key)
            result[key] = value
        return result
    value = json.loads(_read(path, limit).decode('utf-8'), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ProfileError('Expected an owned JSON record: '+str(path))
    return value


def _clean_execution(record):
    active = record.get('job_active_processes_after_cleanup', record.get('job_active_processes_at_parent_exit'))
    return (record.get('status') == 'terminal' and type(record.get('exit_code')) is int and record['exit_code'] == 0
            and type(active) is int and active == 0
            and record.get('assigned_suspended') is True
            and type(record.get('job_total_processes')) is int and record['job_total_processes'] >= 1)


def _trusted_profile(workspace, receipt):
    """Require the desktop controller's clean original-Job receipt and bindings."""
    execution = _json(receipt/'owner/execution.json', 65536)
    argv = execution.get('argv')
    if (not _clean_execution(execution) or not isinstance(argv, list) or any(not isinstance(v, str) for v in argv)
            or any(v.partition('=')[0] in ('--headless', '--test-source', '--seconds') for v in argv)):
        return None
    scripts = [Path(v) for v in argv if Path(v).name == 'client.py']
    if len(scripts) != 1 or not scripts[0].is_absolute():
        return None
    package = scripts[0].parent.resolve(strict=True)
    if Path(execution['cwd']).resolve(strict=True) != package:
        return None
    manifest = _json(package/'package-manifest.json', 2*1024*1024)
    if manifest.get('capabilities') != ['join-only']:
        return None
    files = manifest.get('files')
    if not isinstance(files, list) or len(files) > 10000 or any(not isinstance(x, dict) for x in files):
        return None
    member = [x for x in files if x.get('path') == 'client.py']
    if len(member) != 1 or hashlib.sha256(_read(scripts[0], INI_LIMIT)).hexdigest() != member[0].get('sha256'):
        return None
    log = _read(receipt/'owner/stdout.log', INI_LIMIT).decode('utf-8')
    sessions = [Path(line[9:]).resolve(strict=True) for line in log.splitlines() if line.startswith('Session: ')]
    if len(sessions) != 1 or sessions[0].parent != workspace or re.fullmatch('client-[0-9a-f]{12}', sessions[0].name) is None:
        return None
    run = sessions[0]
    session = _json(run/'session.json', 65536)
    native = session.get('argv', [])
    profile = run/'profile'
    if (session.get('capability') != 'join-only' or '-UserDir='+str(profile) not in native
            or any(v in native for v in ('-nullrhi', '-unattended'))):
        return None
    native_execution = _json(run/'execution/execution.json', 65536)
    if not _clean_execution(native_execution) or native_execution.get('argv') != native:
        return None
    _plain(profile)
    settings = _child(profile, 'Saved/Config/Windows/GameUserSettings.ini')
    if not settings.is_file():
        return None
    raw = _read(settings, INI_LIMIT)
    _, rows = _ini(raw)
    if not any(section and section.casefold() in ('/script/valhalla.valgameusersettings', '/script/engine.gameusersettings') for _, section, _ in rows):
        return None
    # The original owner publishes its terminal receipt after game cleanup.
    # Rank that receipt, not preference mtime (which later tools may touch).
    return {'profile': profile, 'receipt': receipt,
            'terminal_receipt_mtime_ns': (receipt/'owner/execution.json').stat().st_mtime_ns}


def migration_candidate(workspaces):
    candidates = []
    for value in dict.fromkeys(str(Path(p).resolve()) for p in workspaces):
        workspace = Path(value)
        control = workspace/'desktop-control'
        if not control.is_dir():
            continue
        _plain(control)
        receipts = list(control.iterdir())
        if len(receipts) > 256:
            raise ProfileError('Community profile history exceeds256 receipts; no preferences were replaced.')
        for receipt in receipts:
            if not receipt.is_dir() or re.fullmatch('[0-9a-f]{32}', receipt.name) is None:
                continue
            try:
                found = _trusted_profile(workspace, receipt)
            except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                found = None  # Unresolved/foreign receipt is never authority to migrate.
            if found is not None:
                candidates.append(found)
    if not candidates:
        return None
    latest = max(c['terminal_receipt_mtime_ns'] for c in candidates)
    selected = [c for c in candidates if c['terminal_receipt_mtime_ns'] == latest]
    if len(selected) != 1:
        raise ProfileError('Latest clean player-profile receipt is ambiguous; no preferences were replaced.')
    return selected[0]


class ProfileSession:
    def __init__(self, *, mode, workspaces=(), diagnostic=False, root=None, source_game=None, package_root=None,
                 bootstrap_map='/Game/Maps/Active/Drydock/Arena_Drydock_P'):
        if type(diagnostic) is not bool or not isinstance(workspaces, (tuple, list)) or len(workspaces) > 8:
            raise ProfileError('Invalid player-profile session options.')
        self.mode, self.workspaces, self.diagnostic = mode, tuple(workspaces), diagnostic
        if not _valid_bootstrap_map(bootstrap_map):
            raise ProfileError('Invalid community bootstrap map.')
        self.bootstrap_map = bootstrap_map
        self.root = (Path(root) if root is not None else user_profile_root()).resolve()
        for boundary in tuple(workspaces) + tuple(p for p in (source_game, package_root) if p is not None):
            original = Path(boundary).resolve()
            if self.root == original or original in self.root.parents:
                raise ProfileError('Durable player settings must stay outside the game, package and workspaces.')
        self.profile = self.root/'profile'
        self.handle = None
        self.fullscreen_default = True
        self.native_started = False
        self.cleanup_confirmed = False

    def __enter__(self):
        if self.diagnostic:
            return self
        self.root.mkdir(parents=True, exist_ok=True)
        _plain(self.root)
        lock = self.root/'profile.lock'
        if lock.exists(): _plain(lock)
        self.handle = lock.open('a+b')
        os.set_inheritable(self.handle.fileno(), False)
        if lock.stat().st_size == 0:
            self.handle.write(b'\0'); self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close(); self.handle = None
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or getattr(exc, 'winerror', None) in (33, 36):
                raise ProfileBusy('Your community game is already using its saved settings. Close it before starting another game.') from exc
            raise ProfileError('The player-settings lock is unavailable: '+str(exc)) from exc
        try:
            self._prepare()
        except BaseException:
            self._release()
            raise
        return self

    def _prepare(self):
        if os.path.lexists(self.profile): _plain(self.profile)
        if not self.profile.exists():
            chosen = migration_candidate(self.workspaces+(self.root.parent/'sessions',))
            temp = self.root/('profile-initializing-'+uuid.uuid4().hex)
            directory = temp/'Saved/Config/Windows'
            directory.mkdir(parents=True)
            if chosen:
                migrated = []
                for name in MIGRATE_FILES:
                    source = _child(chosen['profile'], 'Saved/Config/Windows/'+name)
                    if source.exists():
                        raw = _read(source, INI_LIMIT); _ini(raw)
                        with (directory/name).open('xb') as stream: stream.write(raw)
                        migrated.append(name)
                (temp/'community-migration.json').write_text(json.dumps({'source_profile':str(chosen['profile']), 'receipt':str(chosen['receipt']), 'files':migrated}), encoding='utf-8')
            if self.profile.exists():
                raise ProfileError('A durable profile appeared during initialization; retained both paths.')
            os.rename(temp, self.profile)
        _plain(self.profile)
        settings = _child(self.profile, 'Saved/Config/Windows/GameUserSettings.ini')
        if settings.exists():
            raw = _read(settings, INI_LIMIT)
            try: _ini(raw)
            except ProfileError:
                _backup(settings, self.root, raw); raise
            self.fullscreen_default = False
        update_bootstrap(self.profile, self.root, self.mode, map_name=self.bootstrap_map)

    def directory(self, run):
        if not self.diagnostic:
            return self.profile
        profile = Path(run)/'profile'
        profile.mkdir()
        update_bootstrap(profile, profile, self.mode, map_name=self.bootstrap_map)
        return profile

    def starting_native(self):
        self.native_started = True

    def confirm_cleanup(self, result):
        if not isinstance(result, dict):
            raise ProfileError('Native cleanup record is unavailable; profile lease retained.')
        active = result.get('job_active_processes_after_cleanup', result.get('job_active_processes_at_parent_exit'))
        self.cleanup_confirmed = type(active) is int and active == 0
        if not self.cleanup_confirmed:
            raise ProfileError('Game cleanup is unconfirmed; the saved-settings lease remains retained.')

    def _release(self):
        if self.handle is not None:
            try:
                if os.name == 'nt':
                    import msvcrt
                    self.handle.seek(0); msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
                self.handle.close()
            except OSError as exc:
                self._retain()
                raise ProfileError('Player-settings lease cleanup failed; ownership retained.') from exc
            self.handle = None

    def _retain(self):
        if not any(lease is self for lease in _RETAINED_LEASES):
            _RETAINED_LEASES.append(self)

    def __exit__(self, kind, value, traceback):
        if self.native_started and not self.cleanup_confirmed and not self.diagnostic:
            self._retain()
            return False
        self._release()
        return False
