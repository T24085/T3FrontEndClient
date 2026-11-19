"""Windows-side game ownership for a native Ubuntu Join Game request."""
from contextlib import suppress
import json
from pathlib import Path
import threading
import time


def status(directory, phase, *, error=None, progress=None):
    temporary = directory/'status.tmp'
    temporary.write_text(json.dumps(dict(status=phase,error=error,progress=progress)),encoding='utf-8')
    temporary.replace(directory/'status.json')


def serve(directory, package, game_dir, workspace, context):
    from direct_client import DirectClient, DirectGame
    from map_sync import MapSync

    request_path = directory/'claimed.json'
    if request_path.stat().st_size > 32768:
        raise ValueError('Invalid Clan Wars handoff size.')
    request = json.loads(request_path.read_bytes())
    request_path.unlink()
    if not 0 <= time.time()-request['issued'] <= 150:
        raise ValueError('The Clan Wars handoff expired.')
    if (directory/'cancel').exists():
        status(directory,'stopped')
        return 0
    lobby = DirectClient(request['connection'], ssl_context=context)
    game = None
    try:
        caps = lobby.capabilities()
        lobby.code, lobby.token, lobby.player_id = request['code'], request['token'], request['player']
        sync = MapSync(lobby,package,workspace)
        sync.start(caps.get('mapFileSync'))
        game = DirectGame(lobby,package,game_dir,workspace,directory/'game',map_sync=sync)
        public = request['role'] == 'public'
        failure = []
        def join():
            try:
                if public:
                    game.start_public(request['name'])
                else:
                    game.start(expected_map=request['map'], expected_match_id=request['match'])
            except Exception as exc:
                failure.append(str(exc))
        launch = threading.Thread(target=join,name='ubuntu-owned-game')
        launch.start()
        next_poll = 0
        last = None
        while True:
            snapshot = game.snapshot()
            phase = snapshot['status']
            cancelled = (directory/'cancel').exists()
            if cancelled:
                game.stop()
            now = time.monotonic()
            if public and not cancelled and phase == 'playing' and now >= next_poll:
                next_poll = now + 2
                with suppress(RuntimeError, OSError):
                    current = game.public_round
                    state = lobby.public_state(renew=True)
                    if (current and state.get('id') == current[0] and state.get('phase') == 'playing'
                            and type(state.get('round')) is int and state['round'] > current[1]):
                        game.continue_public((current[0],state['round']))
            if failure and not launch.is_alive() and phase == 'idle':
                status(directory,'failed',error=failure[0])
                return 1
            if not launch.is_alive() and phase in ('stopped','finished','failed','quarantined'):
                if game.thread is not None and game.thread.is_alive():
                    time.sleep(.25)
                    continue
                status(directory,phase,error=snapshot.get('error') or (failure[0] if failure else None))
                return int(phase in ('failed','quarantined'))
            entry = (phase,snapshot.get('error'),snapshot.get('progress'))
            if entry != last:
                status(directory,'starting' if phase=='idle' else phase,
                       error=entry[1],progress=entry[2])
                last = entry
            time.sleep(.25)
    finally:
        if game is not None:
            game.stop()
            sync.cancelled.set()
        lobby.close()
