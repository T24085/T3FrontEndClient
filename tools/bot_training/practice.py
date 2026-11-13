"""Record demonstrations on a loopback-only High Octane 2026 match."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid


HERE = Path(__file__).resolve().parent
MAP = 'HighOctane2026'
EXE = Path('Topaz/Binaries/Win64/TribesRivals.exe')
MOD = EXE.parent / 'ue4ss/Mods/CommunityLauncher/Scripts/main.lua'
FIELDS = ('segment,time_s,team,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,vz_cm_s,'
          'yaw_deg,pitch_deg,energy,grounded,move_x,move_y,ski_requested,jet_pressed')


def memory_available():
    class Performance(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong)] + [(field, ctypes.c_size_t) for field in
            ('commit', 'limit', 'peak', 'total', 'available', 'cache',
             'kernel', 'paged', 'nonpaged', 'page')] + [
            (field, ctypes.c_ulong) for field in ('handles', 'processes', 'threads')]

    info = Performance()
    if not ctypes.WinDLL('psapi', use_last_error=True).GetPerformanceInfo(
            ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (info.limit - info.commit) * info.page


def private_game(source, game):
    for name in ('Engine', 'Topaz/Plugins', 'Topaz/Assembly', 'Topaz/Content', EXE.parent / 'D3D12'):
        original = (source / name).resolve(strict=True)
        link = game / name
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(original)],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    for folder in ('', 'Topaz', EXE.parent):
        for item in (source / folder).iterdir():
            if item.is_file() and item.suffix.lower() not in ('.log', '.dmp'):
                target = game / folder / item.name
                if item.suffix.lower() in ('.dll', '.exe'):
                    try:
                        os.link(item, target)
                    except OSError as exc:
                        if exc.winerror not in (17, 1142):
                            raise
                        shutil.copy2(item, target)
                else:
                    shutil.copy2(item, target)
    shutil.copytree(source / EXE.parent / 'ue4ss', game / EXE.parent / 'ue4ss',
                    ignore=shutil.ignore_patterns('*.log', '*.dmp'))


def render(text, values):
    def substitute(match):
        value = values[match[1]]
        return json.dumps(value, ensure_ascii=False)

    return re.sub(r'@@([A-Z_]+)@@', substitute, text)


def event_text(folder):
    path = folder / 'events.txt'
    return path.read_text(encoding='utf-8', errors='replace') if path.is_file() else ''


def start(config, smoke=False):
    workspace = Path(config['workspace']).resolve(strict=True)
    baseline = Path(config['host_fixture']).resolve(strict=True)
    package = Path(config['host_package']).resolve(strict=True)
    installed = Path(config['client_package']).resolve(strict=True)
    cached = Path(config['cached_client_session']).resolve(strict=True)
    backend = workspace / 'worktrees/public-ctf-server'
    sys.path[:0] = [str(backend), str(package / 'lib'), str(backend / 'host/lib')]
    from community_maps import declared_definitions
    from host_catalog_runtime import runtime_paths
    from match_roster import render_warm_file
    from native_resource_gate import native_resources
    from owned_native_session import run_owned_job

    definition = declared_definitions(json.loads((baseline / 'package-manifest.json').read_bytes()))[MAP]
    spec = importlib.util.spec_from_file_location('practice_reference', baseline / 'playtest.py')
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    runs = Path(config['runs']).resolve()
    runs.mkdir(parents=True, exist_ok=True)
    out = runs / (time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    out.mkdir()
    print(f'Practice session files: {out}', flush=True)
    definitions, objectives = runtime_paths(package, out, definition)
    lease = uuid.uuid4().hex
    commit = out / 'commit.roster'
    commit.write_text(f"T3ROSTER1\n{lease}\n{MAP}\n1\n127.0.0.2|1|{b'Local Practice'.hex()}\n",
                      encoding='ascii', newline='\n')
    host_template = out / 'host-template.lua'
    render_warm_file(baseline / 'network.lua', host_template, commit, lease, MAP,
                     allow_loopback=True, map_definitions={MAP: definition}, bot_count=0)
    host_text = host_template.read_text(encoding='utf-8')
    turret = '    if not base_kit_tick(gm,gs) then return end'
    if turret in host_text:
        host_text = host_text.replace(turret, '    -- No base turrets in movement practice.', 1)
    client_text = (installed / 'lua/client.lua').read_text(encoding='utf-8')
    anchor = 'local function client_tick(sys)'
    ready = 'if pawnReady then'
    if client_text.count(anchor) != 1 or client_text.count(ready) != 1:
        raise ValueError('The installed client template differs from the local practice adapter.')
    recording = out / 'movement.csv'
    recording.write_text(FIELDS + '\n', encoding='ascii')
    client_text = client_text.replace(anchor, '''
local practiceRecorderStarted=false
local practiceRecorder=assert(loadfile(@@DEMO_SCRIPT@@))()({
 path=@@DEMO_PATH@@,world=@@DEMO_WORLD@@,valid=valid,scope=scope,report=report
})
''' + anchor, 1).replace(ready, ready + '''
        if not practiceRecorderStarted then
            practiceRecorderStarted=true
            local ok, why=pcall(practiceRecorder,pc,gs)
            if not ok then report('BOT_DEMO_ERROR|'..tostring(why):sub(1,350)) end
        end
''', 1)
    host_args = json.loads(Path(config['host_argv']).read_bytes())['argv']
    host_args += ['-httpproxy=127.0.0.1:1', '-DefaultPlatformService=NULL', '-nosteam', '-noSteamV2',
                  '-noeos', f'-Port={port}', '-MULTIHOME=127.0.0.1', '-nobots', '-server']
    client_args = json.loads((cached / 'session.json').read_bytes())['argv']
    client_args += ['-MULTIHOME=127.0.0.2']
    if smoke:
        client_args.remove('-d3d11')
        client_args += ['-nullrhi', '-nosound', '-unattended']
    else:
        client_args += ['-windowed', '-ResX=1280', '-ResY=720', '-NoVSync']

    def stage(role, argv, text, extra):
        folder = out / role
        game = folder / 'game'
        private_game(cached / 'game', game)
        profile = folder / 'profile'
        ini = profile / 'Saved/Config/Windows/Engine.ini'
        ini.parent.mkdir(parents=True)
        game_map = definition.package if role == 'host' else '/Game/Maps/Active/Drydock/Arena_Drydock_P'
        options = '?listen?bUseIPSockets' if role == 'host' else ''
        ini.write_text(f'[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap={game_map}\n'
                       f'GlobalDefaultGameMode={reference.MODE}\nLocalMapOptions=?game={reference.MODE}{options}\n\n'
                       '[/Script/OnlineSubsystemUtils.IpNetDriver]\nMaxPortCountToTry=0\n', encoding='ascii')
        replacements = {'-UserDir=': str(profile), '-abslog=': str(folder / 'game.log'),
                        '-REAResearchScope=': uuid.uuid4().hex}
        for prefix, value in replacements.items():
            if sum(arg.startswith(prefix) for arg in argv) != 1:
                raise ValueError(f'Expected one {prefix} argument in the saved {role} launch.')
            argv = [prefix + value if arg.startswith(prefix) else arg for arg in argv]
        argv[0] = str(game / EXE)
        values = dict(EXPECTED=reference.engine_command_line(argv[2:]), OUTPUT=(folder / 'events.txt').as_posix(),
                      MAP_DEFINITIONS=definitions.as_posix(), OBJECTIVES=objectives.as_posix(), **extra)
        lua_root = (package if role == 'host' else installed) / 'lua'
        files = {'GEOMETRY': 'geometry_runtime', 'SPECTATOR_RUNTIME': 'spectator_client',
                 'SPECTATOR_MATERIAL_RUNTIME': 'spectator_materials'}
        for key in set(re.findall(r'@@([A-Z_]+)@@', text)) - values.keys():
            values[key] = (lua_root / (files.get(key, key.lower()) + '.lua')).resolve(strict=True).as_posix()
        (game / MOD).write_text(render(text, values), encoding='utf-8')
        return argv, game

    env = dict(os.environ, SteamAppId='2687970', SteamGameId='2687970')
    cancel = out / 'cancel.json'
    jobs = {}
    print('Waiting for the local game test slot.', flush=True)
    with native_resources(timeout_ms=60000), ThreadPoolExecutor(max_workers=2) as pool:
        if memory_available() < 5 * 1024**3:
            raise RuntimeError('Close other memory-heavy apps before running the two local game processes.')
        listing = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq TribesRivals.exe', '/FO', 'CSV', '/NH'],
                                 capture_output=True, text=True, check=True)
        if any(row and row[0].lower() == 'tribesrivals.exe' for row in csv.reader(listing.stdout.splitlines())):
            raise RuntimeError('Close the existing TRIBES 3 game before opening local practice.')
        host = stage('host', host_args, host_text, dict(ROLE='host', DESTINATION='', ROTATION_SECONDS=0, MATCH_MAP=MAP))
        client = stage('client', client_args, client_text, dict(
            DESTINATION=f'127.0.0.1:{port}', SHOW_FLAG_INDICATORS=True, STOCK_CLOUD_MAP='', SPECTATOR_ROLE='player',
            MATCH_LEASE='', WATCH_ID='', MUSIC_SETTINGS=(out / 'client/profile/Saved/Config/Windows/GameUserSettings.ini').as_posix(),
            DEMO_SCRIPT=(HERE / 'record.lua').as_posix(), DEMO_PATH=recording.as_posix(), DEMO_WORLD=definition.package))

        def launch(role, staged):
            argv, game = staged
            jobs[role] = pool.submit(run_owned_job, argv, game, env, out / role / 'execution', 3600, cancel)

        try:
            launch('host', host)
            deadline = time.monotonic() + 420
            announced = False
            client_loading = False
            while True:
                host_events, client_events = (event_text(out / role) for role in ('host', 'client'))
                for line in (host_events + '\n' + client_events).splitlines():
                    if line.startswith(('RUNTIME_ERROR|', 'BOT_DEMO_ERROR|')):
                        raise RuntimeError(line)
                if jobs['host'].done():
                    raise RuntimeError('Local host exited. See host/game.log.')
                if 'client' in jobs and jobs['client'].done():
                    if announced and not smoke:
                        break
                    raise RuntimeError('Local client exited before recording. See client/game.log.')
                if 'client' not in jobs and 'WARM_HOST_TIMER_HELD|' in host_events:
                    if memory_available() < int(3.5 * 1024**3):
                        raise RuntimeError('Available commit dropped below the local client reserve.')
                    launch('client', client)
                    client_loading = True
                    print('Local host ready. Loading the practice game.', flush=True)
                if not announced and 'BOT_DEMO_RECORDING' in client_events:
                    announced = True
                    print(f'Recording High Octane (2026). Close the game when done. Data: {recording}', flush=True)
                    if smoke:
                        break
                if not announced and time.monotonic() >= deadline:
                    waiting = 'client recording' if client_loading else 'local host readiness'
                    raise RuntimeError(f'Timed out waiting for {waiting}. See the session game logs.')
                if memory_available() < 1024**3:
                    raise RuntimeError('Available commit dropped below the game reserve.')
                time.sleep(.5)
        finally:
            temp = cancel.with_suffix('.tmp')
            temp.write_text(json.dumps({'cancel': True, 'reason': 'Local practice ended'}), encoding='ascii')
            temp.replace(cancel)
            for role, job in jobs.items():
                result = job.result(timeout=45)
                remaining = result.get('job_active_processes_after_cleanup', result.get('job_active_processes_at_parent_exit'))
                print(f'{role}: {result["status"]}, remaining owned processes: {remaining}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--smoke', action='store_true', help='Check the recorder in a headless local match.')
    options = parser.parse_args()
    start(json.loads(options.config.read_bytes()), options.smoke)
