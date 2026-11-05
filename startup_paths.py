"""One owner for per-user installation choices and implicit staging location."""
import json
import os
from pathlib import Path
from bulk_asset_cache import local_filesystem


def local_directory():
    return Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData/Local')) / 'Tribes3CommunityStarter'


def session_workspace(explicit=None, game_directory=None):
    if explicit is not None:
        return Path(explicit).resolve()
    local = (local_directory() / 'sessions').resolve()
    if game_directory is not None:
        game = Path(game_directory).resolve()
        if (game.drive.casefold() != local.drive.casefold()
                and game.parent.is_dir() and local_filesystem(game.parent) == 'NTFS'):
            # Stay outside the original game while retaining same-volume links.
            return game.parent / 'Tribes3CommunityStarter-sessions' / Path.home().name
    return local


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate installation preference: ' + key)
        result[key] = value
    return result


def installation_preferences():
    path = local_directory() / 'installation.json'
    try:
        with path.open('rb') as stream:
            raw = stream.read(16385)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ValueError('Cannot read local installation preferences: ' + str(path)) from exc
    try:
        if len(raw) > 16384:
            raise ValueError('Installation preferences exceed 16 KiB')
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {'game_directory', 'workspace'}:
            raise ValueError('Expected exactly game_directory and workspace')
        for key, item in value.items():
            if not isinstance(item, str) or not item or '\0' in item or not Path(item).is_absolute():
                raise ValueError('Expected an absolute path for ' + key)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid local installation preferences at ' + str(path) + ': ' + str(exc)) from exc


def installation_options(game_directory=None, workspace=None):
    preferences = installation_preferences()
    game = game_directory if game_directory is not None else preferences.get('game_directory')
    staging = workspace if workspace is not None else preferences.get('workspace')
    if staging is None and game is None:
        from client_support import discover_game
        game = str(discover_game(None))
    return game, session_workspace(staging, game)
