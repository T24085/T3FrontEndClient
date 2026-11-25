"""Package an existing Windows training installation for a second PC."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from itertools import batched
import json
import os
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


HERE = Path(__file__).resolve().parent
PREFIX = 'T3-Bot-Training-Laptop/'
BACKEND_FILES = ('community_maps.py', 'match_roster.py', 'match_roster_legacy_v9.py',
                 'tailnet_identity.py', 'player_names.py', 'verified_file_cache.py',
                 'native_resource_gate.py', 'community_transport.py', 'dynamic_destination.py',
                 'map_sync_contract.py', 'runtime-fixes/warm_host.lua', 'runtime-fixes/match_rules.lua',
                 'runtime-fixes/bot-approaches.json', 'runtime-fixes/bot_flag_approach.lua')


class FolderBundle:
    def __init__(self, root):
        self.root = root

    def destination(self, name):
        return self.root / name.removeprefix(PREFIX)

    def write(self, source, name):
        target = self.destination(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def writestr(self, name, contents):
        target = self.destination(name)
        if name.endswith('/'):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents.encode('utf-8'))


def tree(archive, root, destination, *, game=False):
    for folder, dirs, files in os.walk(root):
        path = Path(folder)
        dirs[:] = [name for name in dirs if name != '__pycache__' and not (path/name).is_symlink()
                   and (name not in ('Saved', 'CrashReportClient') if game else not (path/name).is_junction())]
        for name in files:
            source = path/name
            if not source.is_symlink() and (not game or source.suffix.lower() not in ('.log', '.dmp')):
                archive.write(source, PREFIX+destination+'/'+source.relative_to(root).as_posix())


def json_entry(archive, name, data):
    archive.writestr(PREFIX+name, json.dumps(data, indent=2)+'\n')


def portable_traces(value, sessions):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'trace' and isinstance(item, str):
                path = Path(item)
                if path.is_absolute() and path.is_relative_to(sessions):
                    value[key] = 'Sessions/'+path.relative_to(sessions).as_posix()
            else:
                portable_traces(item, sessions)
    elif isinstance(value, list):
        for item in value:
            portable_traces(item, sessions)


def portable_argv(path):
    args = json.loads(path.read_bytes())['argv']
    transient = ('-UserDir=', '-abslog=', '-REAResearchScope=')
    return ['TribesRivals.exe', *(arg.split('=')[0]+'=relocated' if arg.startswith(transient) else arg for arg in args[1:])]


def game_archive(archive, cache, *, staged=False):
    if not staged:
        tree(archive, cache/'game', 'GameCache/game', game=True)
    json_entry(archive, 'GameCache/session.json', {'argv': portable_argv(cache/'session.json')})


def session_files(sessions):
    return (path for path in sessions.glob('*/*.csv')
            if 'trace' in path.name or '-result-' in path.name or path.name == 'movement.csv')


def pack_history(sessions, output):
    with ThreadPoolExecutor(max_workers=8) as readers, ZipFile(
            output, 'x', compression=ZIP_DEFLATED, compresslevel=3) as archive:
        for paths in batched(session_files(sessions), 128):
            for path, contents in zip(paths, readers.map(Path.read_bytes, paths)):
                archive.writestr(path.relative_to(sessions).as_posix(), contents)


def training_archive(archive, root, config, dashboard, *, folder=False):
    host, fixture, client = (Path(config[key]) for key in ('host_package', 'host_fixture', 'client_package'))
    backend = Path(config['workspace'])/'worktrees/public-ctf-server'
    for name in BACKEND_FILES:
        archive.write(backend/name, PREFIX+'workspace/worktrees/public-ctf-server/'+name)
    for name in ('content', 'lib', 'lua'):
        tree(archive, host/name, 'runtime/host/'+name)
    tree(archive, client/'lua', 'runtime/client/lua')
    python = host/'python' if (host/'python/python.exe').is_file() else client/'python'
    if not (python/'python313.zip').is_file():
        raise FileNotFoundError('A packaged Windows Python 3.13 runtime is required.')
    tree(archive, python, 'python')
    if config.get('map_catalog'):
        archive.write(Path(config['map_catalog']), PREFIX+'runtime/training-catalog.json')
    if config.get('season_runtime'):
        tree(archive, Path(config['season_runtime'])/'lua', 'runtime/season/lua')
    tree(archive, root/'MapOverviews', 'MapOverviews')
    archive.write(fixture/'network.lua', PREFIX+'runtime/fixture/network.lua')
    archive.write(fixture/'playtest.py', PREFIX+'runtime/fixture/playtest.py')
    for profile in fixture.glob('*/bot-approaches.json'):
        archive.write(profile, PREFIX+'runtime/fixture/'+profile.relative_to(fixture).as_posix())
    manifest = json.loads((fixture/'package-manifest.json').read_bytes())
    json_entry(archive, 'runtime/fixture/package-manifest.json',
               {key: manifest[key] for key in ('community_bot_maps', 'community_maps', 'map_definitions')
                if key in manifest})
    json_entry(archive, 'runtime/host-argv.json', {'argv': portable_argv(Path(config['host_argv']))})
    for file in HERE.iterdir():
        if file.suffix in ('.py', '.lua') and not file.name.startswith('test_'):
            archive.write(file, PREFIX+'tools/bot_training/'+file.name)
    archive.write(HERE/'dashboard/serve_dashboard.py', PREFIX+'tools/bot_training/dashboard/serve_dashboard.py')
    archive.write(dashboard, PREFIX+'Dashboard/index.html')
    archive.writestr(PREFIX+'python/TrainingPaths.txt',
                     'python313.zip\n.\n../tools/bot_training\n../runtime/host/lib\n')
    archive.writestr(PREFIX+'Start Training Dashboard.bat', '\r\n'.join((
        '@echo off',
        r'copy /Y "%~dp0python\TrainingPaths.txt" "%~dp0python\python313._pth" >nul',
        r'"%~dp0python\python.exe" -B -u "%~dp0tools\bot_training\laptop_setup.py" %*',
        'if errorlevel 1 pause', '',
    )))
    installation = ('Copy this entire folder to a local NTFS drive on your Windows laptop.\r\n' if folder else
                    'Extract both ZIP files into the same parent folder on a local NTFS drive.\r\n')
    archive.writestr(PREFIX+'README.txt', installation +
                     'Open Steam and sign in on the laptop.\r\n'
                     'Double-click Start Training Dashboard.bat and open the local link it prints.\r\n'
                     'Leave the launcher window open while you train.\r\n'
                     'The folder includes the prepared game cache, Python and the training maps.\r\n'
                     'The dashboard opens while copied replay files are restored on the first launch.\r\n'
                     'The copied training history and queue are a snapshot. Use Resume or Start in the dashboard when ready.\r\n')
    sessions = Path(config['runs'])
    archive.writestr(PREFIX+'Sessions/', '')
    for pattern in ('Campaign-*/**/progress.json', 'DashboardRuns/*/progress.json'):
        for path in root.glob(pattern):
            data = json.loads(path.read_bytes())
            portable_traces(data, sessions)
            json_entry(archive, path.relative_to(root).as_posix(), data)
    runs = root/'DashboardRuns'
    states = {}
    for path in runs.glob('run*/request.json'):
        request = json.loads(path.read_bytes())
        json_entry(archive, path.relative_to(root).as_posix(), request)
        status = path.with_name('status.json')
        try:
            state = json.loads(status.read_bytes())
        except FileNotFoundError:
            state = {'status': 'Interrupted', 'message': 'Snapshot of the desktop run.'}
        states[path.parent.name] = state
    marker = runs/'active-run.txt'
    active = marker.read_text(encoding='ascii').strip() if marker.is_file() else ''
    queued = sorted((state['queued_at'], name) for name, state in states.items() if state['status'] == 'Queued')
    if queued and (active not in states or states[active]['status'] in ('Queued', 'Complete')):
        active = queued[0][1]
        states[active] = {'status': 'Interrupted', 'message': 'Ready to start from the copied queue.'}
    if active in states:
        archive.writestr(PREFIX+'DashboardRuns/active-run.txt', active+'\n')
    for name, state in states.items():
        json_entry(archive, f'DashboardRuns/{name}/status.json', state)
    if folder:
        pack_history(sessions, archive.root/'TrainingHistory.zip')
    else:
        for path in session_files(sessions):
            archive.write(path, PREFIX+'Sessions/'+path.relative_to(sessions).as_posix())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--dashboard', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--game', action='store_true')
    mode.add_argument('--folder', action='store_true')
    parser.add_argument('--staged-game', action='store_true', help='Reuse the materialized game under the output folder.')
    args = parser.parse_args()
    config = json.loads((args.root/'practice.json').read_bytes())
    if not args.game and not args.dashboard:
        parser.error('Supply the current dashboard build.')
    if args.staged_game and not args.folder:
        parser.error('--staged-game requires --folder.')
    if args.folder:
        if args.staged_game:
            exe = args.output/'GameCache/game/Topaz/Binaries/Win64/TribesRivals.exe'
            if not exe.is_file():
                parser.error('The output folder must contain the staged game.')
        else:
            args.output.mkdir(parents=True, exist_ok=False)
        destination = FolderBundle(args.output)
        game_archive(destination, Path(config['cached_client_session']), staged=args.staged_game)
        training_archive(destination, args.root, config, args.dashboard, folder=True)
        print(args.output, flush=True)
        return
    temporary = args.output.with_suffix('.partial')
    with ZipFile(temporary, 'x', compression=ZIP_STORED if args.game else ZIP_DEFLATED,
                 compresslevel=None if args.game else 3) as archive:
        if args.game:
            game_archive(archive, Path(config['cached_client_session']))
        else:
            training_archive(archive, args.root, config, args.dashboard)
    with ZipFile(temporary) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f'Archive CRC check failed for {corrupt}.')
        print(f'Verified {len(archive.infolist())} archive entries.', flush=True)
    os.replace(temporary, args.output)
    print(f'{args.output} ({args.output.stat().st_size:,} bytes)', flush=True)


if __name__ == '__main__':
    main()
