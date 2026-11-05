"""Explicit completed/entered client startup stages; no estimated countdown."""
PREFIX = 'CLIENT_STARTUP|phase='
PHASES = {
    'checking_match': 'Checking the selected match…',
    'preparing_client': 'Finishing game file preparation…',
    'checking_prepared': 'Checking prepared game files…',
    'verifying_maps': 'Checking map files…',
    'verifying_package': 'Checking client files…',
    'finding_game': 'Locating your Steam game…',
    'verifying_game': 'Checking original game files. The first check can take several minutes…',
    'staging_game': 'Preparing your isolated game session…',
    'staging_content': 'Preparing maps and client runtime…',
    'launching_client': 'Starting the game client…',
    'launching_game': 'Opening fullscreen game…',
    'connecting': 'Game started. Waiting for the server and your player…',
    'connecting_spectator': 'Game started. Connecting to the match as a spectator…',
    'loading_spectator': 'Map loaded. Preparing your spectator camera…',
    'loading_match': 'Connected to the match. Loading the map…',
    'loading_player': 'Map loaded. Preparing your player and loadout…',
    'playing': 'Game connected.',
}

def report(phase):
    if phase not in PHASES:
        raise ValueError('Unknown client startup phase')
    print(PREFIX + phase, flush=True)

def observed_phase(lines):
    phase = None
    for line in lines:
        if line.startswith(PREFIX) and line[len(PREFIX):] in PHASES:
            phase = line[len(PREFIX):]
    return phase


def observed_failure(lines):
    """Read the child launcher's existing failure record, without native-exit guesses."""
    prefix = 'Unable to join: '
    failure = None
    for line in lines:
        if line.startswith(prefix) and line[len(prefix):].strip():
            failure = line[len(prefix):]
    return failure


def runtime_phase(lines, *, role='player', match_id=None, watch_id=None):
    if role not in ('player', 'spectator'):
        raise ValueError('Unknown client role')
    phase = None
    for line in lines:
        if line in ('RUNTIME_LOADED|client', 'JOIN_REQUESTED', 'RECONNECTING_TO_FIXED_SERVER'):
            phase = 'connecting_spectator' if role == 'spectator' else 'connecting'
        elif line.startswith('CLIENT_WORLD|') and line[len('CLIENT_WORLD|'):]:
            phase = 'loading_spectator' if role == 'spectator' else 'loading_match'
        elif role == 'player' and line.startswith('LOADOUT_REQUESTED|') and line[len('LOADOUT_REQUESTED|'):].isdigit():
            phase = 'loading_player'
        elif role == 'player' and line == 'REMOTE_PAWN_READY|role=client':
            phase = 'playing'
        elif (role == 'spectator' and match_id and watch_id
              and line.startswith('SPECTATOR_READY|lease=' + match_id + '|watch=' + watch_id + '|')
              and line[len('SPECTATOR_READY|lease=' + match_id + '|watch=' + watch_id + '|'):]):
            phase = 'playing'
    return phase
