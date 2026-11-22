"""Native Ubuntu lobby UI. Steam is contacted only for a requested game."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT/'lib')]
from linux_launcher import APP_ID, prepare_launch, run_in_terminal, windows_path
from ubuntu_startup import exclusive, private_area

MARKER = '-clanwars-ubuntu-join='
ACTIVE = ('starting', 'playing', 'stopping', 'quarantined')


def write_private(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream)


def steam_option():
    return '/bin/sh ' + shlex.quote(str(ROOT/'Start Community Starter.sh')) + ' --ubuntu-dispatch %command%'


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
                    return {'status':'starting','error':None,'progress':'Waiting for Steam to open the game…'}
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
            request = self.state/'joins'/identifier
            request.mkdir(mode=0o700, parents=True)
            with self.lobby.lock:
                # The lobby window keeps polling during preparation. Its requests
                # must use the same host admission as the Proton worker.
                self.lobby.begin_game_attempt()
                details = dict(connection=self.lobby.connection, role=role, issued=time.time(),
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
            self.deadline = time.monotonic() + 120
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
    state = private_area()
    request = state/'joins'/markers[0][len(MARKER):]
    if request.resolve() != request or not request.is_dir():
        raise ValueError('The Clan Wars Steam handoff expired.')
    with exclusive(state/'steam-session.lock'):
        pending = request/'request.json'
        claimed = request/'claimed.json'
        if not pending.is_file() or (request/'cancel').exists() or time.time()-pending.stat().st_mtime > 120:
            pending.unlink(missing_ok=True)
            raise ValueError('The Clan Wars Steam handoff expired. Click Join Game again.')
        pending.rename(claimed)
        from ubuntu_join_worker import status
        log_path = request/'proton.log'
        try:
            status(request, 'starting', progress='Starting Steam Proton…')
            compat = state/'compatdata'
            compat.mkdir(exist_ok=True)
            isolated_env = dict(os.environ, STEAM_COMPAT_DATA_PATH=str(compat))
            argv, env, _ = prepare_launch(ROOT, [part for part in command if part not in markers],
                                         isolated_env, workspace=state/'game-files', state_directory=state)
            dos_root = PureWindowsPath(argv[argv.index('--launch-dir')+1]).anchor
            argv += ['--ubuntu-join', windows_path(dos_root, request)]
            with log_path.open('wb') as log:
                code = run_in_terminal(argv, env, ROOT, log)
            outcome = json.loads((request/'status.json').read_bytes())
            if outcome['status'] in ACTIVE:
                status(request, 'failed', error=f'Proton closed before the game reported a result. Log: {log_path}')
            return code
        except Exception as exc:
            status(request, 'failed', error=f'{exc} — Startup files: {request}')
            return 1
        finally:
            claimed.unlink(missing_ok=True)


def show_starter(lobby, state, on_ready=None):
    import tkinter as tk
    from tkinter import messagebox, ttk
    from desktop_launcher import Desktop
    from direct_client import PublicCTFPanel
    from map_sync import MapSync

    class UbuntuDesktop(Desktop):
        public_panel = None

        def set_capabilities(self, caps):
            super().set_capabilities(dict(caps, spectateEnabled=False))

        def maybe_auto_join(self):
            # Only a deliberate click on Join Game or Join Public CTF starts Proton.
            return

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
        instructions = 'Force a Proton version in TRIBES 3 → Properties → Compatibility. Paste this line into General → Launch Options.'
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
    map_sync = MapSync(lobby, ROOT, state/'game-files')
    app = UbuntuDesktop(window, lobby, lambda current:GameHandoff(current,state), map_sync=map_sync)
    window.title('Clan Wars • Ubuntu Starter Preview')
    app.button(app.sidebar, 'Steam Setup', show_setup, False).pack(fill='x', padx=18, pady=(6,0))
    if lobby.public_supported:
        app.public_panel = PublicCTFPanel(tk, app, lobby)
        app.show_panel('public' if lobby.public_only else 'lobbies')
    revision = json.loads((ROOT/'package-manifest.json').read_bytes()).get('linux_starter_update_revision', 0)
    if revision:
        ttk.Label(app.sidebar, text=f'Linux update {revision}').pack(side='bottom', anchor='w', padx=18)
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
