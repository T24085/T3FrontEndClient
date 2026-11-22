"""Native Ubuntu lobby UI. Steam is contacted only for a requested game."""
import argparse
from base64 import b64encode
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
from linux_launcher import APP_ID, armor_viewport, prepare_launch, run_in_terminal
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


def read_steam_vdf(path):
    with path.open('rb') as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError('Steam config is too large.')
    tokens = (match[0] for match in VDF_TOKEN.finditer(raw.decode('utf-8-sig')) if not match[0].startswith('//'))

    def string(token):
        return re.sub(r'\\(["\\])', r'\1', token[1:-1]) if token.startswith('"') else token

    def block(depth):
        if depth > 16:
            raise ValueError('Steam config has too many nested blocks.')
        entries = {}
        for key in tokens:
            if key == '}' and depth:
                return entries
            value = next(tokens, None)
            if key in ('{', '}') or value in (None, '}'):
                raise ValueError('Steam config is incomplete.')
            entries[string(key).casefold()] = block(depth + 1) if value == '{' else string(value)
        if depth:
            raise ValueError('Steam config is incomplete.')
        return entries

    return block(0)


def read_login_users(path):
    users = read_steam_vdf(path).get('users')
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


def retail_profiles(steam, home):
    from ubuntu_join_worker import IMPORT_INIS
    libraries = set(steam_config_roots(steam, home))
    for root in sorted(libraries):
        try:
            data = read_steam_vdf(root/'steamapps/libraryfolders.vdf').get('libraryfolders', {})
            for key, entry in data.items():
                path = entry.get('path') if isinstance(entry, dict) else entry
                if key.isdecimal() and isinstance(path, str) and Path(path).is_absolute():
                    libraries.add(Path(path))
        except (OSError, ValueError, AttributeError):
            continue
    candidates = set()
    for library in libraries:
        users = library/f'steamapps/compatdata/{APP_ID}/pfx/drive_c/users'
        for config in users.glob('*/AppData/Local/Topaz/Saved/Config/Windows'):
            if any((config/name).is_file() for name in IMPORT_INIS):
                candidates.add(config.resolve())
    return sorted(candidates)


def queue_retail_settings(config, storage):
    from direct_network import write_json
    from player_profile import INI_LIMIT, _read
    from ubuntu_join_worker import IMPORT_FILE, IMPORT_INIS
    files = {name: b64encode(_read(config/name, INI_LIMIT)).decode('ascii') for name in IMPORT_INIS
             if (config/name).is_file()}
    if not files:
        raise ValueError('Choose the retail settings folder containing Input.ini or GameUserSettings.ini.')
    write_json(storage/IMPORT_FILE, files)


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
        self.watch_id = None

    def snapshot(self):
        with self.lock:
            if self.directory is None:
                return {'status':'idle','error':None}
            status_file = self.directory/'status.json'
            try:
                result = json.loads(status_file.read_bytes())
                if result.get('watch_released') and self.watch_id:
                    with self.lobby.lock:
                        self.lobby._watch_tokens.pop(self.watch_id, None)
                return dict(result, role=self.role, watchId=self.watch_id)
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
                if role == 'spectator':
                    token = self.lobby._watch_tokens.get(values['watch_id'])
                    if token is None:
                        request.rmdir()
                        raise CommunityError('This spectator reservation has expired.')
                    values['watch_token'] = token
                else:
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
            self.watch_id = values.get('watch_id')
            return 'starting'

    def start(self, *, expected_map=None, expected_match_id=None):
        return self._send('player', map=expected_map, match=expected_match_id)

    def start_public(self, name):
        return self._send('public', name=name)

    def start_spectating(self, watch_id):
        with self.lock:
            try:
                return self._send('spectator', watch_id=watch_id)
            except Exception:
                try:
                    self.lobby.release_spectator(watch_id)
                except (OSError, ValueError, RuntimeError):
                    if self.snapshot()['status'] not in ACTIVE:
                        self.watch_id = watch_id
                raise

    def stop_spectating(self):
        from community_transport import CommunityError
        with self.lock:
            if self.watch_id is None:
                return
            self.stop()
            if self.snapshot()['status'] in ACTIVE:
                return
            try:
                self.lobby.release_spectator(self.watch_id)
            except CommunityError as exc:
                if exc.code != 'spectator_session_invalid':
                    raise
            self.watch_id = None

    def _cancel(self):
        (self.directory/'cancel').touch()
        try:
            (self.directory/'request.json').unlink()
        except FileNotFoundError:
            return
        from ubuntu_join_worker import status
        status(self.directory, 'stopped')

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
    from tkinter import filedialog, messagebox, ttk
    from desktop_launcher import BG, MUTED, TEXT, Desktop, starter_version
    import direct_client
    from direct_network import VOICE_PROTOCOL, read_json, write_json
    from map_sync import MapSync
    from player_names import display_name
    from ubuntu_join_worker import IMPORT_FILE, IMPORT_RESULT, VOICE_FILE, voice_preferences

    manifest = json.loads((ROOT/'package-manifest.json').read_bytes())
    revision = manifest.get('linux_starter_update_revision', 0)
    build = SOURCE_STARTER_REVISION if revision and SOURCE_STARTER_REVISION else manifest.get('starter_update_revision')
    base_label = starter_version()

    class UbuntuDesktop(Desktop):
        public_panel = None
        armor_panel = None
        tool_tips = None

        def label(self, parent, text, *args, **kwargs):
            if revision and parent is getattr(self, 'sidebar', None) and text == base_label:
                text = f'Build r{build}\nLinux update {revision}' if type(build) is int else f'Linux update {revision}'
                label = super().label(parent, text, *args, **kwargs)
                label.configure(justify='left')
                return label
            return super().label(parent, text, *args, **kwargs)

        def set_capabilities(self, caps):
            lobby.proximity_supported = caps.get('proximityVoice') == VOICE_PROTOCOL
            super().set_capabilities(caps)
            self.refresh_voice_notice()

        def refresh_voice_notice(self):
            notice = getattr(self, 'voice_notice', None)
            if notice is None:
                return
            if lobby.proximity_supported:
                enabled = voice_preferences(storage/VOICE_FILE).get('enabled') is not False
                notice.configure(text='Proximity voice On' if enabled else 'Proximity voice Off')
                if not notice.winfo_manager():
                    notice.pack(anchor='w', pady=(4, 0))
            else:
                notice.pack_forget()

        def close(self):
            if self.tool_tips is not None:
                self.tool_tips.closed.set()
            super().close()

        def show_panel(self, name):
            if self.closing:
                return
            if self.tool_tips is not None:
                tab = {'lobbies': 'create_lobby', 'live': 'lobby_browser', 'public': 'public_ctf'}.get(name, name)
                self.tool_tips.event('open_tab', tab)
            if self.armor_panel is not None:
                self.armor_panel.panel.pack_forget()
            if self.public_panel is not None:
                self.public_panel.panel.pack_forget()
            panel = {'armor': self.armor_panel, 'public': self.public_panel}.get(name)
            if panel is not None:
                self.current_panel = name
                self.lobby_panel.pack_forget()
                self.live_panel.pack_forget()
                if self.maps_panel is not None:
                    self.maps_panel.pack_forget()
                panel.panel.pack(side='left', fill='both', expand=True, padx=32, pady=28)
                if name == 'armor':
                    panel.open()
                return
            super().show_panel(name)

        def show_settings(self):
            previous = getattr(self, 'settings_window', None)
            if previous is not None and previous.winfo_exists():
                previous.lift()
                return
            settings = self.settings_window = tk.Toplevel(window, bg=BG, padx=24, pady=20)
            settings.title('Settings')
            settings.transient(window)
            if self.tool_tips is not None:
                self.tool_tips.event('open_tab', 'settings')

            def note(value):
                tk.Label(settings, textvariable=value, bg=BG, fg=MUTED, anchor='w', justify='left',
                         wraplength=420).pack(fill='x', pady=(4, 10))

            self.label(settings, 'Warrior Name', 16, True).pack(anchor='w')
            self.label(settings, 'Leave blank to use your Steam name.', color=MUTED).pack(anchor='w', pady=(4, 8))
            name = tk.StringVar(settings, warrior_name)
            entry = ttk.Entry(settings, textvariable=name)
            entry.pack(fill='x')
            name_status = tk.StringVar(settings)

            def save_name():
                nonlocal warrior_name
                raw = name.get().strip()
                try:
                    value = display_name(raw) if raw else ''
                    write_json(name_file, {'name': value})
                except (OSError, ValueError) as exc:
                    name_status.set(str(exc))
                    return
                warrior_name = value
                name.set(value)
                self.name.set(value)
                if not value:
                    fill_steam_name()
                name_status.set('Name saved for your next join.' if value else 'Using your Steam name.')

            self.button(settings, 'Save name', save_name, False).pack(anchor='w', pady=(8, 0))
            entry.bind('<Return>', lambda _event: save_name())
            note(name_status)

            self.label(settings, 'Game settings', 16, True).pack(anchor='w')
            detail = self.label(settings, 'Import your retail key bindings, sensitivity, and game options. '
                                'The import runs before your next match and backs up replaced settings.', color=MUTED)
            detail.configure(wraplength=420, justify='left')
            detail.pack(anchor='w', pady=(5, 8))
            import_status = tk.StringVar(settings)
            try:
                if (storage/IMPORT_FILE).is_file():
                    import_status.set('Retail settings are queued for your next game.')
                else:
                    import_status.set(read_json(storage/IMPORT_RESULT, 4096)['message'])
            except (OSError, ValueError, KeyError, TypeError):
                pass

            def import_settings():
                if self.controls_busy or self.game_status in ACTIVE:
                    import_status.set('Close TRIBES 3 and wait for the launcher to finish its current action.')
                    return
                try:
                    profiles = retail_profiles(shutil.which('steam'), home)
                    if len(profiles) == 1:
                        config = profiles[0]
                    else:
                        initial = profiles[0] if profiles else home
                        selected = filedialog.askdirectory(parent=settings, initialdir=initial, mustexist=True,
                                                          title='Choose the retail Saved/Config/Windows folder')
                        if not selected:
                            return
                        config = Path(selected)
                    with exclusive(state/'steam-session.lock'):
                        queue_retail_settings(config, storage)
                except (OSError, ValueError) as exc:
                    import_status.set(str(exc))
                    return
                import_status.set('Retail settings are queued for your next game.')

            self.button(settings, 'Import settings from retail', import_settings).pack(anchor='w')
            note(import_status)

            if lobby.proximity_supported:
                self.label(settings, 'Proximity voice', 16, True).pack(anchor='w')
                keys = direct_client.PTT_KEY_NAMES
                key_names = {name: code for code, name in keys.items()}
                prefs = voice_preferences(storage/VOICE_FILE)
                enabled = tk.BooleanVar(settings, prefs.get('enabled') is not False)
                saved_key = prefs.get('key')
                key = tk.StringVar(settings, keys[saved_key] if type(saved_key) is int and saved_key in keys
                                   else keys[direct_client.DEFAULT_PTT_KEY])
                voice_status = tk.StringVar(settings)

                def save_voice():
                    try:
                        write_json(storage/VOICE_FILE, {'enabled': enabled.get(), 'key': key_names[key.get()]})
                    except (OSError, ValueError, KeyError) as exc:
                        voice_status.set(str(exc))
                        return
                    voice_status.set('Proximity voice on.' if enabled.get() else 'Proximity voice off.')
                    self.refresh_voice_notice()
                    if self.tool_tips is not None:
                        self.tool_tips.event('setting_changed', 'proximity_voice')

                row = tk.Frame(settings, bg=BG)
                row.pack(anchor='w', pady=(6, 0))
                tk.Checkbutton(row, text='Enable proximity voice', variable=enabled, command=save_voice,
                               bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT,
                               selectcolor='#20374a').pack(side='left')
                picker = ttk.Combobox(row, textvariable=key, values=tuple(key_names), state='readonly', width=14)
                picker.pack(side='left', padx=(12, 0))
                picker.bind('<<ComboboxSelected>>', lambda _event: save_voice())
                note(voice_status)

            self.button(settings, 'About this launcher', lambda: messagebox.showinfo(
                'About this launcher',
                f'Clan Wars connects to {lobby.authority} for lobbies and matches. '
                'It uses your Steam copy of TRIBES 3 in a separate Proton session and verifies community downloads.',
                parent=settings), False).pack(anchor='w')
            settings.bind('<Escape>', lambda _event: settings.destroy())

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
    storage = snap_state(common) if common else state
    workspace = storage/'game-files'
    name_file = state/'warrior-name.json'
    try:
        warrior_name = display_name(read_json(name_file, 1024)['name'])
    except (OSError, ValueError, KeyError, TypeError):
        warrior_name = ''
    map_sync = MapSync(lobby, ROOT, workspace)
    app = UbuntuDesktop(window, lobby, lambda current:GameHandoff(current,state), map_sync=map_sync)

    def fill_steam_name():
        if app.closing or app.name.get().strip():
            return
        persona = warrior_name or steam_persona(shutil.which('steam'), home)
        if persona:
            app.name.set(persona)
        else:
            window.after(2500, fill_steam_name)

    fill_steam_name()
    window.title('Clan Wars • Ubuntu Starter Preview')
    app.button(app.sidebar, 'Steam Setup', show_setup, False).pack(fill='x', padx=18, pady=(6,0))
    if lobby.public_supported:
        app.public_panel = direct_client.PublicCTFPanel(tk, app, lobby)
        app.show_panel('public' if lobby.public_only else 'lobbies')
    armor_panel = getattr(direct_client, 'ArmorPanel', None)
    if armor_panel is not None and getattr(lobby, 'armor_supported', False):
        viewport = armor_viewport(tk, direct_client.ArmorViewport)

        class UbuntuArmorPanel(armor_panel):
            def select_suit(self, event=None):
                super().select_suit(event)
                key = self.current_selection()
                if (key in direct_client.ARMOR_MODEL_BLOBS and key not in self.models
                        and key != self.displayed_model):
                    self.model_status.configure(text='Loading 3D suit…')
                    self.submit(key)

            def show_model(self, key):
                model = self.models.get(key)
                if model is None:
                    return False
                try:
                    if self.viewport is None:
                        self.viewport = viewport(self.model_frame)
                    self.present_model(model)
                except (AttributeError, OSError, ValueError, tk.TclError):
                    self.model_frame.pack_forget()
                    self.model_status.pack(fill='both', expand=True)
                    return False
                self.displayed_model = key
                return True

        app.armor_panel = UbuntuArmorPanel(tk, app, lobby)
    app.settings_nav = app.button(app.sidebar, 'Settings', app.show_settings, False)
    app.settings_nav.pack(fill='x', padx=18, pady=(6, 0))
    launcher_tips = getattr(direct_client, 'LauncherTips', None)
    if launcher_tips is not None:
        sidebar_bg = app.sidebar.cget('bg')
        tips = tk.Frame(app.sidebar, bg=sidebar_bg)
        tips.pack(fill='x', padx=20, pady=(14, 0))
        app.label(tips, 'Tool Tips', 10, True, bg=sidebar_bg).pack(anchor='w')
        app.tool_tips = launcher_tips(tk, app, lobby, state, tips)
        app.voice_notice = app.label(tips, '', 9, color=MUTED, bg=sidebar_bg)
        app.refresh_voice_notice()
        app.tool_tips.tip_region.pack(fill='x')
        tk.Button(tips, text='Key Bindings Import in Settings', command=app.show_settings,
                  bg=sidebar_bg, fg=MUTED, activebackground=sidebar_bg, activeforeground=TEXT,
                  relief='flat', bd=0, padx=0, pady=2, anchor='w', cursor='hand2',
                  font=('Segoe UI', 9)).pack(anchor='w')
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
