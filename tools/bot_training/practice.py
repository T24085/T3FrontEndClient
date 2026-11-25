"""Record demonstrations on a loopback-only High Octane 2026 match."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
import csv
import ctypes
from dataclasses import replace
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
MAX_TRAINING_BOTS = 24
EXE = Path('Topaz/Binaries/Win64/TribesRivals.exe')
MOD = EXE.parent / 'ue4ss/Mods/CommunityLauncher/Scripts/main.lua'
MISSING_GAME_CACHE = 'The local training game cache is missing. Rebuild it before resuming.'
FIELDS = ('segment,time_s,team,x_cm,y_cm,z_cm,vx_cm_s,vy_cm_s,vz_cm_s,'
          'yaw_deg,pitch_deg,energy,grounded,move_x,move_y,ski_requested,jet_pressed')


class NativeMemoryBusy(RuntimeError):
    pass


class TrainingStopped(Exception):
    pass


class TrainingPaused(Exception):
    pass


def check_training_stop():
    signal = os.environ.get('T3_DASHBOARD_STOP_FILE')
    if signal and Path(signal).is_file():
        raise TrainingStopped()


def check_between_matches():
    check_training_stop()
    signal = os.environ.get('T3_DASHBOARD_STOP_FILE')
    if signal and Path(signal).with_name('pause.request').is_file():
        raise TrainingPaused()


def training_wait(seconds):
    if not os.environ.get('T3_DASHBOARD_STOP_FILE'):
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        check_between_matches()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))


@contextmanager
def training_resources(native_resources, busy_error):
    if not os.environ.get('T3_DASHBOARD_STOP_FILE'):
        with native_resources(timeout_ms=60000):
            yield
        return
    deadline = time.monotonic() + 60
    with ExitStack() as stack:
        while True:
            check_between_matches()
            try:
                stack.enter_context(native_resources(timeout_ms=500))
            except busy_error:
                if time.monotonic() >= deadline:
                    raise
            else:
                break
        check_between_matches()
        yield


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


def training_manifest(config):
    path = config.get('map_catalog') or Path(config['host_fixture']) / 'package-manifest.json'
    return json.loads(Path(path).read_bytes())


def training_maps(config):
    game = Path(config['cached_client_session']) / 'game'
    if not (game / EXE).is_file():
        return {}
    backend = Path(config['workspace']) / 'worktrees/public-ctf-server'
    sys.path.insert(0, str(backend))
    try:
        from community_maps import declared_definitions
    finally:
        sys.path.pop(0)
    manifest = training_manifest(config)
    labels = manifest.get('map_labels', {}) if config.get('map_catalog') else {}
    content = game / 'Topaz/Content/Maps/Community'
    navigable = set(manifest.get('community_bot_maps', ())) | {MAP}
    return {
        name: replace(definition, label=labels.get(name, definition.label))
        for name, definition in declared_definitions(manifest).items()
        if definition.native or ((config.get('map_catalog') or name in navigable) and
            (content / definition.asset_group / (definition.level + '.umap')).is_file())
    }


def repair_training_power_registry(host_text):
    """Normalize duplicate native turret registrations in the isolated season host."""
    start = ' local function initial_registries(gm,gs,counts,snapshot)\n'
    end = ' local function registries(gm,gs,counts)\n'
    if start not in host_text:
        return host_text
    before, _, tail = host_text.partition(start)
    registry, boundary, after = tail.partition(end)
    if not boundary or host_text.count(start) != 1:
        raise ValueError('The season host power registry differs from the training adapter.')
    edits = (
        ('  local result,problems={},{}',
         '  local result,problems={},{}\n  local poweredOrder,duplicateTurrets={},0'),
        ("    if n>spec.limit then reject('base_power_initial_registry_exceeds_owned_slots='..spec.field) end",
         "    if spec.key~='p' and n>spec.limit then\n"
         "     reject('base_power_initial_registry_exceeds_owned_slots='..spec.field)\n"
         "    end"),
        ("      assert(not result[spec.key][key],'duplicate_actor')\n"
         '      result[spec.key][key]=actor',
         "      if result[spec.key][key] and spec.key=='p' and entry.kind=='turret' then\n"
         '       duplicateTurrets=duplicateTurrets+1\n'
         '       return\n'
         '      end\n'
         "      assert(not result[spec.key][key],'duplicate_actor')\n"
         '      result[spec.key][key]=actor\n'
         "      if spec.key=='p' then poweredOrder[#poweredOrder+1]=actor end"),
        ('  return result\n',
         "  assert(#poweredOrder<=counts.powered,'base_power_initial_registry_exceeds_owned_slots=gm.GeneratorPoweredActors')\n"
         '  if duplicateTurrets>0 then\n'
         '   local array=gm.GeneratorPoweredActors\n'
         "   local label='gm.GeneratorPoweredActors'\n"
         '   array:Empty()\n'
         "   assert(array:GetArrayNum()==0,'base_power_training_registry_reset_failed')\n"
         '   for index,actor in ipairs(poweredOrder) do array[index]=actor end\n'
         '   local count,actual=weak_array(array,label,gm:GetWorld(),counts.powered)\n'
         "   assert(count==#poweredOrder,'base_power_training_registry_count_changed')\n"
         '   for _,actor in ipairs(poweredOrder) do\n'
         "    assert(same(actual[actor:GetAddress()],actor),'base_power_weak_conversion_failed='..label)\n"
         '   end\n'
         "   report('BASE_POWER_TRAINING_DUPLICATE_TURRETS_REMOVED|count='..duplicateTurrets)\n"
         '  end\n'
         '  return result\n'),
    )
    for old, new in edits:
        if registry.count(old) != 1:
            raise ValueError('The season host power registry differs from the training adapter.')
        registry = registry.replace(old, new, 1)
    return before + start + registry + end + after


def start(config, smoke=False, trainer=None):
    check_between_matches()
    playable = trainer is not None and trainer.live_player
    local_client = trainer is None or playable
    record_player = trainer is None or (playable and getattr(trainer,'record_player',False))
    cached = Path(config['cached_client_session']).resolve()
    if not (cached / 'game' / EXE).is_file():
        raise RuntimeError(MISSING_GAME_CACHE)
    workspace = Path(config['workspace']).resolve(strict=True)
    baseline = Path(config['host_fixture']).resolve(strict=True)
    package = Path(config['host_package']).resolve(strict=True)
    backend = workspace / 'worktrees/public-ctf-server'
    sys.path[:0] = [str(backend), str(package / 'lib'), str(backend / 'host/lib')]
    from host_catalog_runtime import runtime_paths
    from match_roster import render_warm_file
    from native_resource_gate import NativeResourceBusy, native_resources
    from owned_native_session import run_owned_job

    map_id = config.get('training_map', MAP)
    definition = training_maps(config).get(map_id)
    if definition is None:
        raise ValueError('The selected map is unavailable for local bot training.')
    spec = importlib.util.spec_from_file_location('practice_reference', baseline / 'playtest.py')
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    if not reference.running_image('steam.exe'):
        raise RuntimeError('Open Steam and sign in before starting local practice.')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    destination = f'127.0.0.1:{port}'
    runs = Path(config['runs']).resolve()
    runs.mkdir(parents=True, exist_ok=True)
    prefix = 'playtest-' if playable else 'training-' if trainer else ''
    out = runs / (prefix + time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    out.mkdir()
    print(f'Practice session files: {out}', flush=True)
    if config.get('map_catalog'):
        adapter = training_manifest(config).get('training_adapters', {}).get(map_id)
        definitions, objectives = runtime_paths(package, out, definition, adapter_kind=adapter, label=definition.label)
    else:
        definitions, objectives = runtime_paths(package, out, definition)
    lease = uuid.uuid4().hex
    commit = out / 'commit.roster'
    human_team = getattr(trainer,'human_team',1) if local_client else 2
    commit.write_text(f"T3ROSTER1\n{lease}\n{map_id}\n1\n127.0.0.2|{human_team}|{b'Local Practice'.hex()}\n",
                      encoding='ascii', newline='\n')
    host_template = out / 'host-template.lua'
    season_runtime = config.get('season_runtime') if getattr(trainer, 'capture_limit', None) else None
    host_lua = Path(season_runtime) / 'lua' if season_runtime else package / 'lua'
    network = host_lua / 'network.lua' if season_runtime else baseline / 'network.lua'
    render_warm_file(network, host_template, commit, lease, map_id,
                     allow_loopback=True, map_definitions={map_id: definition},
                     bot_count=getattr(trainer, 'template_bot_count', trainer.bot_count) if trainer else 0)
    host_text = host_template.read_text(encoding='utf-8')
    turret = '    if not base_kit_tick(gm,gs) then return end'
    if season_runtime:
        host_text = repair_training_power_registry(host_text)
    elif turret in host_text:
        host_text = host_text.replace(turret, '    -- No base turrets in movement practice.', 1)
    if trainer:
        trainer.map_id = map_id
        trainer.base_equipment = bool(season_runtime)
        host_text = trainer.instrument(host_text, out)
    if local_client:
        installed = Path(config['client_package']).resolve(strict=True)
        client_text = (installed / 'lua/client.lua').read_text(encoding='utf-8')
    if record_player:
        anchor = 'local function client_tick(sys)'
        ready = '    if pawnReady then\n'
        if client_text.count(anchor) != 1 or client_text.count(ready) != 1:
            raise ValueError('The installed client template differs from the local practice adapter.')
        recording = out / 'movement.csv'
        recording.write_text(FIELDS + '\n', encoding='ascii')
        client_text = client_text.replace(anchor, '''
local practiceRecorderStarted=false
local practiceRecorder=assert(loadfile(@@DEMO_SCRIPT@@))()({
 path=@@DEMO_PATH@@,world=@@DEMO_WORLD@@,team=@@DEMO_TEAM@@,valid=valid,scope=scope,report=report
})
''' + anchor, 1).replace(ready, ready + '''        if not practiceRecorderStarted then
            practiceRecorderStarted=true
            local ok, why=pcall(practiceRecorder,pc,gs)
            if not ok then report('BOT_DEMO_ERROR|'..tostring(why):sub(1,350)) end
        end
''', 1)
    host_args = json.loads(Path(config['host_argv']).read_bytes())['argv']
    host_args += ['-httpproxy=127.0.0.1:1', '-DefaultPlatformService=NULL', '-nosteam', '-noSteamV2',
                  '-noeos', f'-Port={port}', '-MULTIHOME=127.0.0.1', '-nobots', '-server']
    if local_client:
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
        engine_settings = (f'[/Script/EngineSettings.GameMapsSettings]\nGameDefaultMap={game_map}\n'
                           f'GlobalDefaultGameMode={reference.MODE}\nLocalMapOptions=?game={reference.MODE}{options}\n\n'
                           '[/Script/OnlineSubsystemUtils.IpNetDriver]\nMaxPortCountToTry=0\n')
        if playable and role == 'client':
            # The game's hardware defaults reload during startup, so cap allocations at engine priority.
            engine_settings += ('\n[SystemSettings]\nr.Streaming.PoolSize=384\n'
                                'r.Streaming.MaxTempMemoryAllowed=32\nr.Streaming.MipBias=2\n'
                                'r.ShadowQuality=0\nr.VolumetricCloud=0\n')
            (ini.parent/'GameUserSettings.ini').write_text(
                '[ScalabilityGroups]\n' + ''.join(f'sg.{name}Quality=0\n' for name in (
                    'ViewDistance', 'AntiAliasing', 'Shadow', 'GlobalIllumination', 'Reflection',
                    'PostProcess', 'Texture', 'Effects', 'Foliage', 'Shading'))
                + '\n[/Script/Engine.GameUserSettings]\nVersion=5\n', encoding='ascii')
        ini.write_text(engine_settings, encoding='ascii')
        replacements = {'-UserDir=': str(profile), '-abslog=': str(folder / 'game.log'),
                        '-REAResearchScope=': uuid.uuid4().hex}
        for prefix, value in replacements.items():
            if sum(arg.startswith(prefix) for arg in argv) != 1:
                raise ValueError(f'Expected one {prefix} argument in the saved {role} launch.')
            argv = [prefix + value if arg.startswith(prefix) else arg for arg in argv]
        argv[0] = str(game / EXE)
        values = dict(EXPECTED=reference.engine_command_line(argv[2:]), OUTPUT=(folder / 'events.txt').as_posix(),
                      MAP_DEFINITIONS=definitions.as_posix(), OBJECTIVES=objectives.as_posix(), **extra)
        if role == 'client':
            values.update(GAME_CONTENT=(game/'Topaz/Content').as_posix(),MAP_SOUNDTRACK=False)
        lua_root = host_lua if role == 'host' else installed / 'lua'
        files = {'GEOMETRY': 'geometry_runtime', 'SPECTATOR_RUNTIME': 'spectator_client',
                 'SPECTATOR_MATERIAL_RUNTIME': 'spectator_materials'}
        for key in set(re.findall(r'@@([A-Z_]+)@@', text)) - values.keys():
            values[key] = (lua_root / (files.get(key, key.lower()) + '.lua')).resolve(strict=True).as_posix()
        mod = game / MOD
        mod.parent.mkdir(parents=True, exist_ok=True)
        mod.write_text(render(text, values), encoding='utf-8')
        mods_list = mod.parents[2] / 'mods.txt'
        if not mods_list.is_file():
            mods_list.write_text('CommunityLauncher : 1\n', encoding='utf-8')
        return argv, game

    env = dict(os.environ, SteamAppId='2687970', SteamGameId='2687970')
    cancel = out / 'cancel.json'
    jobs = {}
    print('Waiting for the local game test slot.', flush=True)
    with training_resources(native_resources, NativeResourceBusy), ThreadPoolExecutor(max_workers=2) as pool:
        if memory_available() < 5 * 1024**3:
            raise NativeMemoryBusy('Waiting for 5 GiB of available Windows commit for local practice.')
        listing = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq TribesRivals.exe', '/FO', 'CSV', '/NH'],
                                 capture_output=True, text=True, check=True)
        if any(row and row[0].lower() == 'tribesrivals.exe' for row in csv.reader(listing.stdout.splitlines())):
            raise RuntimeError('Close the existing TRIBES 3 game before opening local practice.')
        host = stage('host', host_args, host_text, dict(ROLE='host', DESTINATION='', ROTATION_SECONDS=0, MATCH_MAP=map_id))
        recorder = dict(
            DEMO_SCRIPT=(HERE / 'record.lua').as_posix(), DEMO_PATH=(out/'movement.csv').as_posix(),
            DEMO_WORLD=definition.package,DEMO_TEAM=human_team) if record_player else {}
        client = stage('client', client_args, client_text, dict(
            DESTINATION=destination, SHOW_FLAG_INDICATORS=True, STOCK_CLOUD_MAP='', SPECTATOR_ROLE='player',
            MATCH_LEASE='', WATCH_ID='', MUSIC_SETTINGS=(out / 'client/profile/Saved/Config/Windows/GameUserSettings.ini').as_posix(),
            **recorder)) if local_client else None

        def launch(role, staged):
            argv, game = staged
            jobs[role] = pool.submit(run_owned_job, argv, game, env, out / role / 'execution', 3600, cancel)

        try:
            check_between_matches()
            launch('host', host)
            if not local_client:
                trainer.run(out, jobs['host'])
                return
            deadline = time.monotonic() + 420
            announced = False
            client_loading = False
            while True:
                host_events, client_events = (event_text(out / role) for role in ('host', 'client'))
                for line in (host_events + '\n' + client_events).splitlines():
                    if line.startswith(('RUNTIME_ERROR|', 'BOT_DEMO_ERROR|', 'BOT_TRAIN_ERROR|')):
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
                if (not announced and playable and 'REMOTE_PAWN_READY' in client_events
                        and f'MATCH_RULES_BOTS_READY|count={trainer.bot_count}' in host_events):
                    announced = True
                    side = 'Blue' if human_team == 1 else 'Red'
                    print(f'Playable match ready on {definition.label}. You are on {side}. Close the game when done.',flush=True)
                    if record_player:
                        print(f'Movement recording: {recording}',flush=True)
                elif not announced and not playable and 'BOT_DEMO_RECORDING' in client_events:
                    announced = True
                    print(f'Recording {definition.label}. Close the game when done. Data: {recording}', flush=True)
                if smoke and announced and (not record_player or 'BOT_DEMO_RECORDING' in client_events):
                    break
                if not announced and time.monotonic() >= deadline:
                    waiting = ('player and bot readiness' if playable else 'client recording') if client_loading else 'local host readiness'
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
                if os.environ.get('T3_DASHBOARD_STOP_FILE') and remaining != 0:
                    raise RuntimeError('Training game cleanup could not be verified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--smoke', action='store_true', help='Check the recorder in a headless local match.')
    options = parser.parse_args()
    start(json.loads(options.config.read_bytes()), options.smoke)
