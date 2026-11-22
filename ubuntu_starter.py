"""Native Ubuntu lobby UI. Steam is contacted only for a requested game."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT/'lib')]
from linux_launcher import APP_ID, prepare_launch, run_in_terminal
from ubuntu_startup import exclusive, private_area

MARKER = '-clanwars-ubuntu-join='
ACTIVE = ('starting', 'playing', 'stopping', 'quarantined')
HANDOFF_WAIT = 600
SNAP_LOCK = 'host-steam-session.lock'
SOURCE_STARTER_REVISION = None
VDF_TOKEN = re.compile(r'//[^\r\n]*|"(?:\\.|[^"\\\r\n])*"|[{}]|[^\s{}"]+')


def write_private(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream)


def steam_option():
    return '/bin/sh ' + shlex.quote(str(ROOT/'Start Community Starter.sh')) + ' --ubuntu-dispatch %command%'


def steam_snap_common(steam, home):
    if steam and (Path(steam).parent == Path('/snap/bin') or Path(steam).resolve().name == 'snap'):
        return home/'snap/steam/common'
    return None


def snap_state(common):
    if not common.is_absolute():
        raise ValueError('The Steam Snap data folder must be absolute.')
    state = common/'.local/share/ClanWarsUbuntuStarter'
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Clan Wars Steam Snap data must be private to your Linux user.')
    return state


def join_state(state, steam, home):
    common = steam_snap_common(steam, home)
    if common is None:
        return state
    target = snap_state(common)
    # Both namespaces must lock the same inode. The Snap can open its own
    # link while the native launcher and updater keep using the original.
    native_lock = state/'steam-session.lock'
    fd = os.open(native_lock, os.O_CREAT | os.O_RDONLY | os.O_NOFOLLOW, 0o600)
    try:
        lock = target/SNAP_LOCK
        try:
            os.link(native_lock, lock, follow_symlinks=False)
        except FileExistsError:
            pass
        info = lock.lstat()
        native = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or (info.st_dev, info.st_ino) != (native.st_dev, native.st_ino)):
            raise ValueError('The Steam Snap game-session lock does not match Clan Wars.')
    except OSError as exc:
        raise ValueError('Could not share the Clan Wars game-session lock with Steam Snap. '
                         'Keep Clan Wars Linux data on the same volume as your home directory.') from exc
    finally:
        os.close(fd)
    return target


def steam_config_roots(steam, home):
    common = steam_snap_common(steam, home)
    homes = (common, common.parent/'current') if common is not None else (home,)
    if common is None:
        yield Path(os.environ.get('XDG_DATA_HOME') or home/'.local/share')/'Steam'
    for steam_home in homes:
        for relative in ('.local/share/Steam', '.steam/root', '.steam/steam', '.steam/debian-installation', 'Steam'):
            yield steam_home/relative


def read_login_users(path):
    with path.open('rb') as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError('Steam login cache is too large.')
    tokens = (match[0] for match in VDF_TOKEN.finditer(raw.decode('utf-8-sig')) if not match[0].startswith('//'))

    def string(token):
        return re.sub(r'\\(["\\])', r'\1', token[1:-1]) if token.startswith('"') else token

    def block(depth):
        if depth > 16:
            raise ValueError('Steam login cache has too many nested blocks.')
        entries = {}
        for key in tokens:
            if key == '}' and depth:
                return entries
            value = next(tokens, None)
            if key in ('{', '}') or value in (None, '}'):
                raise ValueError('Steam login cache is incomplete.')
            entries[string(key).casefold()] = block(depth + 1) if value == '{' else string(value)
        if depth:
            raise ValueError('Steam login cache is incomplete.')
        return entries

    users = block(0).get('users')
    if not isinstance(users, dict):
        return []
    return [account for steam_id, account in users.items()
            if re.fullmatch('[0-9]{17}', steam_id) and isinstance(account, dict)]


def steam_persona(steam, home):
    """Read an unambiguous display name from the selected Steam installation."""
    from player_names import display_name
    seen = set()
    for root in steam_config_roots(steam, home):
        try:
            path = (root/'config/loginusers.vdf').resolve()
            if path in seen:
                continue
            seen.add(path)
            accounts = read_login_users(path)
            candidates = [account for account in accounts if account.get('mostrecent') == '1'] or accounts
            if len(candidates) == 1:
                return display_name(candidates[0].get('personaname'))
        except (OSError, RuntimeError, ValueError):
            continue
    return None


class GameHandoff:
    def __init__(self, lobby, state, *, launch=subprocess.Popen):
        self.lobby = lobby
        self.state = state
        self.launch = launch
        self.lock = threading.RLock()
        self.directory = None
        self.deadline = 0
        self.role = 'player'
        self.public_round = None

    def snapshot(self):
        with self.lock:
            if self.directory is None:
                return {'status':'idle','error':None}
            status_file = self.directory/'status.json'
            try:
                return json.loads(status_file.read_bytes())
            except FileNotFoundError:
                if time.monotonic() <= self.deadline:
                    return {'status':'starting','error':None,
                            'progress':'Waiting for Steam. First-time shader processing can take several minutes.'}
                self._cancel()
                return {'status':'failed','error':'Steam did not hand off the game. Check Clan Wars Steam Setup.'}

    def _send(self, role, **values):
        from community_transport import CommunityError
        with self.lock:
            if self.snapshot()['status'] in ACTIVE:
                raise CommunityError('A Clan Wars game is already open.')
            steam = shutil.which('steam')
            if steam is None:
                raise CommunityError('Install native Steam on Ubuntu to join a game.')
            identifier = uuid.uuid4().hex
            request = join_state(self.state, steam, Path.home())/'joins'/identifier
            request.mkdir(mode=0o700, parents=True)
            with self.lobby.lock:
                # The lobby window keeps polling during preparation. Its requests
                # must use the same host admission as the Proton worker.
                self.lobby.begin_game_attempt()
                details = dict(connection=self.lobby.connection, role=role,
                               code=self.lobby.code, token=self.lobby.token, player=self.lobby.player_id,
                               direct_session=self.lobby.direct_session,
                               **values)
            write_private(request/'request.json', details)
            try:
                self.launch([steam, '-applaunch', APP_ID, MARKER+identifier],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
            except OSError:
                (request/'request.json').unlink(missing_ok=True)
                request.rmdir()
                raise
            self.directory = request
            self.deadline = time.monotonic() + HANDOFF_WAIT
            self.role = role
            return 'starting'

    def start(self, *, expected_map=None, expected_match_id=None):
        return self._send('player', map=expected_map, match=expected_match_id)

    def start_public(self, name):
        return self._send('public', name=name)

    def _cancel(self):
        (self.directory/'cancel').touch()
        (self.directory/'request.json').unlink(missing_ok=True)

    def stop(self):
        with self.lock:
            if self.directory is not None and self.snapshot()['status'] in ACTIVE:
                self._cancel()


def dispatch(command):
    """Preserve ordinary Steam Play. Consume a short-lived local Join Game request once."""
    if command[:1] == ['--']:
        command = command[1:]
    markers = [part for part in command if part.startswith(MARKER)]
    if not markers:
        if not command:
            raise ValueError('Steam did not supply a game command.')
        os.execvp(command[0], command)
    if len(markers) != 1 or not re.fullmatch('[0-9a-f]{32}', markers[0][len(MARKER):]):
        raise ValueError('The Clan Wars Steam handoff is invalid.')
    common = os.environ.get('SNAP_USER_COMMON') if os.environ.get('SNAP_NAME') == 'steam' else None
    state = snap_state(Path(common)) if common else private_area()
    request = state/'joins'/markers[0][len(MARKER):]
    if request.resolve() != request or not request.is_dir():
        raise ValueError('The Clan Wars Steam handoff expired.')
    lock = state/(SNAP_LOCK if common else 'steam-session.lock')
    if common and not lock.is_file():
        raise ValueError('The Steam Snap game-session lock is missing. Reopen Clan Wars and click Join Game.')
    with exclusive(lock):
        pending = request/'request.json'
        claimed = request/'claimed.json'
        if not pending.is_file() or (request/'cancel').exists() or time.time()-pending.stat().st_mtime > HANDOFF_WAIT:
            pending.unlink(missing_ok=True)
            raise ValueError('The Clan Wars Steam handoff expired. Click Join Game again.')
        pending.rename(claimed)
        os.utime(claimed, None)
        from ubuntu_join_worker import status
        log_path = request/'proton.log'
        try:
            status(request, 'starting', progress='Starting Steam Proton…')
            compat = state/'compatdata'
            compat.mkdir(exist_ok=True)
            isolated_env = dict(os.environ, STEAM_COMPAT_DATA_PATH=str(compat))
            argv, env, session = prepare_launch(ROOT, [part for part in command if part not in markers],
                                               isolated_env, workspace=state/'game-files', state_directory=state,
                                               join_directory=request)
            with log_path.open('wb') as log:
                code = run_in_terminal(argv, env, ROOT, log)
            outcome = json.loads((request/'status.json').read_bytes())
            if outcome['status'] in ACTIVE:
                bridge_log = session/'bridge.log'
                diagnostic = bridge_log if bridge_log.is_file() else log_path
                status(request, 'failed', error=f'Proton exited with code {code} before reporting game status. '
                                                f'Log: {diagnostic}')
            return code
        except Exception as exc:
            status(request, 'failed', error=f'{exc} — Startup files: {request}')
            return 1
        finally:
            claimed.unlink(missing_ok=True)


def show_starter(lobby, state, on_ready=None):
    import tkinter as tk
    from tkinter import messagebox, ttk
    from desktop_launcher import Desktop, starter_version
    from direct_client import PublicCTFPanel
    from map_sync import MapSync

    manifest = json.loads((ROOT/'package-manifest.json').read_bytes())
    revision = manifest.get('linux_starter_update_revision', 0)
    build = SOURCE_STARTER_REVISION if revision and SOURCE_STARTER_REVISION else manifest.get('starter_update_revision')
    base_label = starter_version()

    class UbuntuDesktop(Desktop):
        public_panel = None

        def label(self, parent, text, *args, **kwargs):
            if revision and parent is getattr(self, 'sidebar', None) and text == base_label:
                text = f'Build r{build}\nLinux update {revision}' if type(build) is int else f'Linux update {revision}'
                label = super().label(parent, text, *args, **kwargs)
                label.configure(justify='left')
                return label
            return super().label(parent, text, *args, **kwargs)

        def set_capabilities(self, caps):
            super().set_capabilities(dict(caps, spectateEnabled=False))

        def show_panel(self, name):
            if self.closing:
                return
            if self.public_panel is not None:
                self.public_panel.panel.pack_forget()
                if name == 'public':
                    self.current_panel = name
                    self.lobby_panel.pack_forget()
                    self.live_panel.pack_forget()
                    self.public_panel.panel.pack(side='left', fill='both', expand=True, padx=32, pady=28)
                    return
            super().show_panel(name)

    def show_setup():
        setup = tk.Toplevel(window)
        setup.title('Steam Setup')
        instructions = ('Open Steam and sign in before your first join. Force a Proton version in '
                        'TRIBES 3 → Properties → Compatibility. Paste this line into General → Launch Options. '
                        'Once you are on a team, Clan Wars opens the game when the match is ready.')
        ttk.Label(setup, text=instructions, wraplength=520).pack(padx=18, pady=12)
        field = ttk.Entry(setup, width=82)
        field.insert(0, steam_option())
        field.state(['readonly'])
        field.pack(padx=18)
        def copy():
            window.clipboard_clear()
            window.clipboard_append(steam_option())
            field.selection_range(0, 'end')
        ttk.Button(setup, text='Copy Launch Option', command=copy).pack(pady=12)

    try:
        window = tk.Tk()
    except tk.TclError as exc:
        raise ValueError('Open Clan Wars from your Ubuntu desktop session.') from exc
    steam = shutil.which('steam')
    home = Path.home()
    common = steam_snap_common(steam, home)
    workspace = (snap_state(common) if common else state)/'game-files'
    map_sync = MapSync(lobby, ROOT, workspace)
    app = UbuntuDesktop(window, lobby, lambda current:GameHandoff(current,state), map_sync=map_sync)

    def fill_steam_name():
        if app.closing or app.name.get().strip():
            return
        persona = steam_persona(shutil.which('steam'), home)
        if persona:
            app.name.set(persona)
        else:
            window.after(2500, fill_steam_name)

    fill_steam_name()
    window.title('Clan Wars • Ubuntu Starter Preview')
    app.button(app.sidebar, 'Steam Setup', show_setup, False).pack(fill='x', padx=18, pady=(6,0))
    if lobby.public_supported:
        app.public_panel = PublicCTFPanel(tk, app, lobby)
        app.show_panel('public' if lobby.public_only else 'lobbies')
    if on_ready is not None:
        window.update_idletasks()
        on_ready()
    window.mainloop()
    if getattr(app, 'close_worker', None):
        app.close_worker.join()


def main(args=None, *, owned_state=None, on_ready=None):
    os.umask(0o077)
    args = list(sys.argv[1:] if args is None else args)
    if args[:1] == ['--dispatch']:
        return dispatch(args[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--steam-option', action='store_true')
    modes.add_argument('--check-lobby', action='store_true')
    parsed = parser.parse_args(args)
    if parsed.steam_option:
        print(steam_option())
        return 0
    from direct_client import DirectClient, group_connection
    state = private_area() if owned_state is None else owned_state
    with exclusive(state/'starter.lock') if owned_state is None else nullcontext():
        lobby = DirectClient(group_connection(ROOT,state))
        try:
            capabilities = lobby.capabilities()
            if parsed.check_lobby:
                lobby.live_matches()
                print(f'Connected to Clan Wars. {len(lobby.server_maps)} maps; '
                      f'Public CTF: {capabilities.get("publicCTF") is True}. Proton was not started.')
            else:
                show_starter(lobby,state,on_ready)
        finally:
            lobby.close()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Clan Wars Ubuntu Starter: {exc}',file=sys.stderr)
        sys.exit(1)
