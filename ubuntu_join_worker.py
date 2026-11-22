"""Windows-side game ownership for a native Ubuntu Join Game request."""
from contextlib import suppress
from base64 import b64decode
import json
from pathlib import Path
import re
import threading
import time
from tempfile import TemporaryDirectory


VOICE_FILE = 'proximity-voice.json'
IMPORT_FILE = 'retail-settings-import.json'
IMPORT_RESULT = 'retail-settings-result.json'
IMPORT_INIS = ('Input.ini', 'GameUserSettings.ini')
IMPORT_LIMIT = 3 * 1024 * 1024


def voice_preferences(path):
    from direct_network import read_json
    try:
        value = read_json(path, 1024)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def apply_retail_import(state, directory):
    from direct_network import read_json, write_json
    from player_profile import CONFIG_DIRECTORY, INI_LIMIT, ProfileError, import_retail_settings
    pending = state/IMPORT_FILE
    try:
        data = read_json(pending, IMPORT_LIMIT)
    except FileNotFoundError:
        return
    except (OSError, ValueError) as exc:
        message = f'Could not read the queued retail settings: {exc}'
    else:
        try:
            if not isinstance(data, dict) or not data or not data.keys() <= set(IMPORT_INIS):
                raise ProfileError('Invalid queued retail settings.')
            with TemporaryDirectory(dir=directory) as temporary:
                local = Path(temporary)
                config = local/'Topaz'/CONFIG_DIRECTORY
                config.mkdir(parents=True)
                for name, encoded in data.items():
                    raw = b64decode(encoded, validate=True)
                    if len(raw) > INI_LIMIT:
                        raise ProfileError('Retail settings exceed their size limit.')
                    (config/name).write_bytes(raw)
                changed = import_retail_settings(retail_local_app_data=local)
            message = ('Retail settings imported.' if changed else 'Community settings already match retail.')
        except (OSError, TypeError, ValueError) as exc:
            message = f'Retail settings were not imported: {exc}'
    write_json(state/IMPORT_RESULT, {'message': message})
    pending.unlink(missing_ok=True)


def status(directory, phase, *, error=None, progress=None, watch_released=False):
    temporary = directory/'status.tmp'
    temporary.write_text(json.dumps(dict(status=phase,error=error,progress=progress,
                                         watch_released=watch_released)),encoding='utf-8')
    temporary.replace(directory/'status.json')


def serve(directory: Path, package: Path, game_dir: Path, workspace: Path, context):
    from direct_client import DirectClient, DirectGame
    from map_sync import MapSync

    request_path = directory/'claimed.json'
    info = request_path.stat()
    if info.st_size > 32768:
        raise ValueError('Invalid Clan Wars handoff size.')
    request = json.loads(request_path.read_bytes())
    request_path.unlink()
    if not 0 <= time.time() - info.st_mtime <= 300:
        raise ValueError('The Clan Wars handoff expired.')
    if (directory/'cancel').exists():
        status(directory,'stopped')
        return 0
    public = request['role'] == 'public'
    team = request.get('team', 'auto') if public else 'auto'
    if team not in ('auto', 'blue', 'red'):
        raise ValueError('Invalid Public CTF team choice.')
    session = request.get('direct_session')
    client_type = DirectClient
    if session is not None:
        if not isinstance(session, str) or re.fullmatch('[0-9a-f]{32}', session) is None:
            raise ValueError('Invalid Clan Wars handoff admission.')

        class HandoffClient(DirectClient):
            def begin_game_attempt(self):
                # Keep the GUI's admission identity when resetting owned sockets.
                with self.lock:
                    super().begin_game_attempt()
                    self.direct_session = session

        client_type = HandoffClient
    lobby = client_type(request['connection'], ssl_context=context)
    if session is not None:
        lobby.direct_session = session
    game = None
    spectator = request['role'] == 'spectator'
    try:
        if spectator:
            watch_id, token = request.get('watch_id'), request.get('watch_token')
            if (not isinstance(watch_id, str) or not re.fullmatch('[A-Za-z0-9_-]{16,64}', watch_id)
                    or not isinstance(token, str) or not token.isascii() or not 32 <= len(token) <= 128):
                raise ValueError('Invalid spectator handoff.')
            lobby._watch_tokens[watch_id] = token
        caps = lobby.capabilities()
        lobby.code, lobby.token, lobby.player_id = request['code'], request['token'], request['player']
        state = directory.parent.parent
        voice_path = state/VOICE_FILE
        if (state/IMPORT_FILE).is_file():
            try:
                apply_retail_import(state, directory)
            except OSError as exc:
                print(f'Could not finish the retail settings import: {exc}', flush=True)
        previous_voice = None

        def refresh_voice():
            nonlocal previous_voice
            if not getattr(lobby, 'proximity_supported', False):
                return
            from direct_client import DEFAULT_PTT_KEY, PTT_KEY_NAMES
            preferences = voice_preferences(voice_path)
            key = preferences.get('key', DEFAULT_PTT_KEY)
            choice = (key if type(key) is int and key in PTT_KEY_NAMES else DEFAULT_PTT_KEY,
                      preferences.get('enabled') is not False)
            if choice != previous_voice:
                lobby.bind_proximity_key(choice[0])
                lobby.set_proximity_voice(choice[1])
                previous_voice = choice

        refresh_voice()
        sync = MapSync(lobby,package,workspace)
        if hasattr(sync, 'session_enabled'):
            sync.start(caps.get('mapFileSync'), session_version=caps.get('mapSessionSync'))
        else:
            sync.start(caps.get('mapFileSync'))
        # StableGame binds the desktop Job receipt to this workspace path.
        game = DirectGame(lobby, package, game_dir, workspace,
                          workspace/'direct-desktop-control', map_sync=sync)
        failure = []
        def join():
            try:
                if public:
                    if team == 'auto':
                        game.start_public(request['name'])
                    else:
                        game.start_public(request['name'], team=team)
                elif spectator:
                    game.start_spectating(watch_id)
                else:
                    game.start(expected_map=request['map'], expected_match_id=request['match'])
            except Exception as exc:
                failure.append(str(exc))
        launch = threading.Thread(target=join,name='ubuntu-owned-game')
        launch.start()
        next_poll = 0
        next_voice = 0
        last = None
        while True:
            snapshot = game.snapshot()
            phase = snapshot['status']
            cancelled = (directory/'cancel').exists()
            if cancelled:
                game.stop()
            now = time.monotonic()
            if now >= next_voice:
                refresh_voice()
                next_voice = now + 1
            if public and not cancelled and phase == 'playing' and now >= next_poll:
                next_poll = now + 2
                with suppress(RuntimeError, OSError):
                    current = game.public_round
                    state = lobby.public_state(renew=True)
                    if (current and state.get('id') == current[0] and state.get('phase') == 'playing'
                            and type(state.get('round')) is int and state['round'] > current[1]):
                        game.continue_public((current[0],state['round']))
            if failure and not launch.is_alive() and phase == 'idle':
                status(directory,'failed',error=failure[0],
                       watch_released=spectator and watch_id not in lobby._watch_tokens)
                return 1
            if not launch.is_alive() and phase in ('stopped','finished','failed','quarantined'):
                if game.thread is not None and game.thread.is_alive():
                    time.sleep(.25)
                    continue
                status(directory,phase,error=snapshot.get('error') or (failure[0] if failure else None),
                       watch_released=spectator and watch_id not in lobby._watch_tokens)
                return int(phase in ('failed','quarantined'))
            entry = (phase,snapshot.get('error'),snapshot.get('progress'))
            if entry != last:
                status(directory,'starting' if phase=='idle' else phase,
                       error=entry[1],progress=entry[2])
                last = entry
            time.sleep(.25)
    finally:
        try:
            if game is not None:
                game.stop()
                if spectator:
                    with suppress(RuntimeError, OSError):
                        game.stop_spectating()
                sync.cancelled.set()
        finally:
            lobby.close()
