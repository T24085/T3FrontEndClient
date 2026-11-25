"""Canonical packaged client entry, copied as client.py by candidate builders.

Prepared-client baseline: frozen Worldbuilding-20261102-r1/client.py,
SHA256 3baeb559c717aaad2316cdd2298e9c8e521cf373f87c358a398064dbaf8ce190.
Source manifest SHA256 740081ed79694c486fcff871b4e5ff3329100e5f7407eaf01985d3ed4c44a009.
"""
import argparse
from contextlib import ExitStack
import json
import os
import re
from startup_progress import report as startup_progress
from startup_paths import installation_options
from pathlib import Path
import sys
import threading
import uuid
from dynamic_destination import ISOLATED_TEST_SOURCES,destination as validate_destination
from runtime_health import runtime_failure
from client_support import (ROOT, REL, engine_command_line, save,
                            verify_package, discover_game, verify_game, running_image)

MODE = '/Game/Topaz/Game/BP_TopazGameMode_CTF_Persistent_BotBackfill.BP_TopazGameMode_CTF_Persistent_BotBackfill_C'
SPECTATOR_CONTRACT = 'native-spectator-v1'
STOCK_CLOUD_MAPS = frozenset({
    'Damnation2026', 'HighOctane2026', 'KatabaticMyrkwood', 'Rollercoaster2026',
    'Scarabrae2026', 'Snowblind2026', 'SnowblindBlizzard2026', 'Stonehenge2026',
})

# The signed Direct release can refresh weather independently of the archive.
# A full archive can also supply the runtime and map descriptors on its own.
_SIGNED_WEATHER_MODULE = None

_SIGNED_SOUNDTRACK_PLAYER = None


def weather_runtime_path(root, run, package):
    if _SIGNED_WEATHER_MODULE is not None:
        path = run / 'weather.lua'
        with path.open('xb') as output:
            output.write(_SIGNED_WEATHER_MODULE)
        return path
    if any(row['path'] == 'lua/weather.lua' for row in package['files']):
        return root / 'lua/weather.lua'
    return root / 'lua/snowblind_weather.lua'

def write_map_definitions(root, run, definitions, selected, package, *, public=False, objectives=None, minimap=None):
    """Extend the map catalog with descriptors verified during map preparation."""
    from hashlib import sha256
    from community_maps import BY_ID, lua_map_definitions
    from map_sync_contract import map_objective_rows, minimap_payload, png_dimensions

    if public:
        generated = run / 'public-maps.lua'
        bundled = root / 'lua/community_maps.lua'
        lines = [f'local maps=assert(loadfile({json.dumps(bundled.as_posix(), ensure_ascii=False)}))()']
        for key in sorted(definitions.keys() - BY_ID.keys()):
            definition = definitions[key]
            world = f'{definition.package}.{definition.level}:'
            lines.append(f'maps[{json.dumps(key)}]={{name={json.dumps(key)},package={json.dumps(definition.package)},'
                         f'world={json.dumps(world)},native=true,'
                         'native_world_settings_class="/Script/Valhalla.ValWorldSettings"}')
        generated.write_text('\n'.join([*lines, 'return maps', '']), encoding='utf-8')
    else:
        generated = lua_map_definitions(root, run, selected)

    selected_maps = definitions.values() if public else (() if selected is None else (selected,))
    files = {row['path']: row for row in package['files']}
    downloaded = map_objective_rows(objectives, definitions) if objectives is not None else {}
    adapters = []
    for definition in selected_maps:
        name = f'lua/{definition.id}/objectives.lua'
        if definition.native:
            continue
        row = downloaded.get(name)
        source_root = run / 'downloaded-objectives'
        if objectives is None:
            row = files.get(name)  # Older full archives bundled verified objectives here.
            source_root = root
        if row is None:
            continue
        path = source_root / name
        if path.resolve(strict=True) != path or path.is_symlink() or not 0 < row['bytes'] <= 256 * 1024:
            raise ValueError(f'Invalid map-local objectives file: {name}')
        with path.open('rb') as stream:
            raw = stream.read(row['bytes'] + 1)
        if len(raw) != row['bytes'] or sha256(raw).hexdigest() != row['sha256']:
            raise ValueError(f'Map-local objectives failed package verification: {name}')
        source = run / 'map-descriptors' / definition.id / 'objectives.lua'
        source.parent.mkdir(parents=True, exist_ok=True)
        with source.open('xb') as output:
            output.write(raw)
        adapters.append((definition.id, source))

    calls = [f'load_weather({json.dumps(map_id)}, {json.dumps(source.as_posix(), ensure_ascii=False)})'
             for map_id, source in adapters]
    if minimap is not None and selected is not None:
        entry = minimap_payload(selected.id, minimap)
        settings = entry['settings'].copy()
        settings.pop('image', None)
        image = entry['image']
        if image is not None:
            path = run / 'minimap.png'
            try:
                if path.resolve(strict=True) != path or path.is_symlink() or path.is_junction():
                    raise ValueError('Minimap graphic escaped the prepared session.')
                with path.open('rb') as stream:
                    raw = stream.read(image['bytes'] + 1)
                if len(raw) != image['bytes'] or sha256(raw).hexdigest() != image['sha256']:
                    raise ValueError('Minimap graphic no longer matches the prepared session.')
                png_dimensions(raw[:33])
                settings['image_file'] = path.as_posix()
            except (OSError, ValueError):
                pass  # The selected map can still use its live map capture.
        if 'image_file' not in settings:
            settings.pop('image_bounds', None)
        calls.append(f'maps[{json.dumps(selected.id)}].minimap={_minimap_lua(settings)}')
    if not calls:
        return generated
    result = run / 'catalog-weather.lua'
    result.write_text(f'local maps=assert(loadfile({json.dumps(generated.as_posix(), ensure_ascii=False)}))()\n'
                      + _MAP_WEATHER_LUA + '\n'.join([*calls, 'return maps', '']), encoding='utf-8')
    return result


def _minimap_lua(value):
    """Write the strictly validated framing data as a Lua table literal."""
    if isinstance(value, dict):
        return '{' + ','.join(f'[{json.dumps(key)}]={_minimap_lua(item)}' for key, item in value.items()) + '}'
    if isinstance(value, list):
        return '{' + ','.join(_minimap_lua(item) for item in value) + '}'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


_MAP_WEATHER_LUA = """
local function music_route(music)
 if music==nil then return end
 assert(type(music)=='table','map_music_contract')
 for key in pairs(music) do
  assert(key=='track' or key=='playlist' or key=='first','map_music_contract')
 end
 if music.track~=nil then
  assert(type(music.track)=='string' and music.playlist==nil and music.first==nil,'map_music_contract')
  local tracks={['t2-badlands']=true,['t2-desert']=true,['t2-ice']=true,['t2-lush']=true,['t2-volcano']=true,
                ['rollercoaster']=true}
  local number=tonumber(music.track:match('^t1%-(%d%d)$'))
  assert(tracks[music.track] or (number and number>=1 and number<=10),'map_music_contract')
  return (music.track:gsub('-','_'))
 end
 local first=music.first
 assert(music.playlist=='t1' and type(first)=='number' and first%1==0 and first>=1 and first<=10,
        'map_music_contract')
 return 'playlist_t1_'..string.format('%d',first)
end

local function apply_weather(id,path)
 local row=assert(maps[id],'weather_catalog_map_missing')
 local env={assert=assert,type=type,ipairs=ipairs,pairs=pairs,setmetatable=setmetatable,
            string={format=string.format}}
 local adapter, metadata=assert(loadfile(path,'t',env))()
 if type(adapter)=='function' and type(metadata)=='table' then adapter=metadata end
 if type(adapter)~='table' then return end
 if id:match('^DraftT2%d%d%d$') and type(adapter.editor_layout)=='table' then
  adapter=adapter.editor_layout
 end
 local authored,layout=adapter.descriptor
 if type(authored)=='function' then
  authored=authored({name=id,package=row.package,world=row.world})
  assert(type(authored)=='table' and authored.name==id and authored.package==row.package
         and authored.world==row.world,'weather_catalog_map_identity')
  layout=authored.base_layout
 elseif adapter.format==1 and (adapter.music~=nil or adapter.weather~=nil or adapter.liquids~=nil or adapter.emergency_lighting~=nil or adapter.hide_minimap~=nil
     or (type(adapter.layout)=='table' and adapter.layout.radars_per_team~=nil)) then
  assert(adapter.map_id==id and adapter.package==row.package and adapter.world==row.world,
         'weather_catalog_map_identity')
  authored=adapter
  layout=authored.layout
 else return end
 local radars
 if type(layout)=='table' then radars=layout.radars_per_team end
 assert(radars==nil or (type(radars)=='number' and radars%1==0 and radars>=0 and radars<=10),'radar_catalog_count_required')
 local hide=authored.hide_minimap
 assert(hide==nil or hide==false or (hide==true and radars==0),'radar_catalog_hide_requires_no_radars')
 row.radars_per_team=radars
 row.hide_minimap=hide
 if authored.weather~=nil then
  assert(authored.weather==false or type(authored.weather)=='table','weather_catalog_config_required')
  row.weather=authored.weather or nil
  row.weather_authored=true
 end
 if authored.liquids~=nil then
  if type(authored.liquids)=='table' then
   row.liquids=authored.liquids
   row.liquid_profile_packs=authored.liquid_profile_packs
  else
   print('Map objectives ignored invalid liquids for '..id)
  end
 end
 if authored.emergency_lighting~=nil then
  assert(type(authored.emergency_lighting)=='boolean','emergency_lighting_setting_required')
  row.emergency_lighting=authored.emergency_lighting
 end
 if id:match('^DraftT2%d%d%d$') and type(layout)=='table' and layout.powered_interiors~=nil then
  row.interior_power={interiors=layout.powered_interiors,groups=layout.power_groups,entries=layout.entries}
 end
 row.music_route=music_route(authored.music)
end
local function load_weather(id,path)
 local ok,err=pcall(apply_weather,id,path)
 if not ok then print('Map objectives could not configure client options for '..id..': '..tostring(err)) end
end
"""


def renderer_arguments(*, headless, fullscreen, test_render_profile):
    if headless:
        return ['-nullrhi', '-nosound', '-unattended']
    if test_render_profile:
        # Keep UMG and the native renderer active for the two-client HUD replay.
        return ['-d3d11', '-windowed', '-resx=960', '-resy=540', '-forceres', '-nosound',
                '-ini:Engine:[SystemSettings]:t.MaxFPS=30',
                '-ini:Engine:[SystemSettings]:r.Streaming.PoolSize=128',
                '-ini:Engine:[SystemSettings]:r.Streaming.MaxTempMemoryAllowed=32',
                '-ini:Engine:[SystemSettings]:r.ShadowQuality=0',
                '-ini:Engine:[SystemSettings]:r.VolumetricCloud=0']
    return ['-d3d11', *(['-fullscreen'] if fullscreen else [])]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--prepared')
    parser.add_argument('--prepared-sha256')
    parser.add_argument('--map-revision', help=argparse.SUPPRESS)
    parser.add_argument('--expected-map')
    parser.add_argument('--expected-content-hash')
    parser.add_argument('--spectate', action='store_true')
    parser.add_argument('--public-session', action='store_true')
    parser.add_argument('--show-flag-indicators', action='store_true')
    parser.add_argument('--match-id')
    parser.add_argument('--watch-id')
    parser.add_argument('--test-source', choices=ISOLATED_TEST_SOURCES, help=argparse.SUPPRESS)
    parser.add_argument('--game-dir')
    parser.add_argument('--workspace')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--rehash', action='store_true')
    parser.add_argument('--headless', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--test-render-profile', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--seconds', type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.test_render_profile and (not args.test_source or args.headless or args.prepare_only or args.check):
        raise ValueError('The test render profile requires a rendered isolated match join.')
    if args.public_session and (args.spectate or args.prepare_only or args.check or not args.expected_map):
        raise ValueError('Public CTF requires an admitted match and its verified map.')
    if args.spectate:
        if (args.prepare_only or args.check or args.expected_map is None or args.expected_content_hash is None
                or not re.fullmatch('[0-9a-f]{32}', args.match_id or '')
                or not re.fullmatch('[A-Za-z0-9_-]{16,64}', args.watch_id or '')):
            raise ValueError('Spectating requires the exact admitted match, watcher and map fingerprint.')
    elif args.match_id is not None or args.watch_id is not None:
        raise ValueError('Watcher identity is only valid for a spectator session.')
    args.game_dir, selected_workspace = installation_options(args.game_dir, args.workspace)
    from client_preparation import CONTRACT, stage, consume
    from startup_timing import StartupTiming
    startup = StartupTiming()
    if bool(args.prepared) != bool(args.prepared_sha256):
        raise ValueError('Prepared client requires its exact descriptor and digest.')
    if args.prepare_only and (args.prepared or args.endpoint or args.check):
        raise ValueError('File preparation cannot join a match.')
    if args.map_revision is not None and not args.prepare_only:
        raise ValueError('A map revision must go through owned file preparation.')
    if not args.prepare_only and not args.endpoint:
        raise ValueError('The lobby must provide the selected match endpoint.')
    if args.game_dir is None:
        source = discover_game(None)
    else:
        source = discover_game(args.game_dir)
    workspace = selected_workspace
    if workspace == source or source in workspace.parents:
        raise ValueError('Session workspace must be outside the original game folder.')
    workspace.mkdir(parents=True, exist_ok=True)
    from verified_file_cache import enable_bulk_receipts
    if not args.prepared and not args.rehash:
        enable_bulk_receipts(ROOT, workspace)
    if ((args.expected_map is None) != (args.expected_content_hash is None)):
        raise ValueError('The lobby must provide both the selected map and content fingerprint.')
    if args.expected_content_hash is not None and not re.fullmatch('[0-9a-f]{64}',args.expected_content_hash):
        raise ValueError('Invalid expected map content fingerprint.')
    if args.prepared:
        if args.rehash or args.check:
            raise ValueError('A prepared join cannot change verification policy.')
        startup_progress('checking_prepared')
        with startup.phase('prepared-validation'):
            prepared=consume(ROOT,source,workspace,args.prepared,args.prepared_sha256,
                             expected_map=args.expected_map,expected_content_hash=args.expected_content_hash)
        verification=prepared['verification'];run=Path(prepared['run']);game=run/'game'
        private_executable_sha256=prepared['private_executable_sha256']
        package=json.loads((ROOT/'package-manifest.json').read_text())
    else:
        startup_progress('verifying_package')
        with startup.phase('package-verification'):
            from map_sync import has_session_revision
            if has_session_revision(workspace, args.map_revision):
                from verified_file_cache import verify_package as verify_client_package
                package = verify_client_package(ROOT, skip_cooked=True)
            else:
                package = verify_package()
        startup_progress('verifying_game')
        with startup.phase('original-verification'):
            manifest,identities,verification=verify_game(source,workspace,args.rehash)
        from map_catalog import verified_catalog
        map_overlay, custom_maps, objectives_downloaded, minimap = None, None, False, None
        with startup.phase('map-verification'):
            if args.map_revision is None:
                catalog = verified_catalog(ROOT)
            else:
                from map_sync import load_overlay
                (map_overlay, catalog, custom_maps, objectives_downloaded, minimap) = load_overlay(
                    workspace, args.map_revision, package, with_minimap=True)
        if args.expected_map is not None and catalog.get(args.expected_map)!=args.expected_content_hash:
            raise ValueError('Your map files do not match this match. Update the community client.')
        if args.check:
            print(json.dumps(dict(build=package['build_id'],game=str(source),verification=verification,capability='join-only'),indent=2))
            return
        startup_progress('staging_game')
        with startup.phase('client-preparation'):
            descriptor=stage(ROOT,source,workspace,package,manifest,identities,verification,catalog=catalog,map_overlay=map_overlay,
                             custom_maps=custom_maps, objectives_downloaded=objectives_downloaded, minimap=minimap,
                             emit=lambda line:print(line,flush=True))
        if args.prepare_only:return
        prepared=consume(ROOT,source,workspace,descriptor['path'],descriptor['sha256'],
                         expected_map=args.expected_map,expected_content_hash=args.expected_content_hash)
        verification=prepared['verification'];run=Path(prepared['run']);game=run/'game'
        private_executable_sha256=prepared['private_executable_sha256']
    contract=package.get('startup_contract')
    if contract not in (None,'verified-child-map-v1',CONTRACT):
        raise ValueError('Unsupported client startup contract.')
    if contract in ('verified-child-map-v1',CONTRACT) and args.expected_map is None:
        raise ValueError('The lobby must provide the selected map and content fingerprint.')
    if args.spectate and package.get('spectator_contract') != SPECTATOR_CONTRACT:
        raise ValueError('This client does not support the native spectator contract. Update the community client.')
    policy=json.loads((ROOT/'connection-policy.json').read_text(encoding='utf-8'))
    destination=validate_destination(args.endpoint,policy,test_source=args.test_source)
    if not running_image('steam.exe'):
        raise RuntimeError('Start Steam and sign in first.')
    from local_http_proxy import loopback_http_failure_preflight
    loopback_http_failure_preflight()
    from player_profile import ProfileSession
    from client_bootstrap import apply as bootstrap_runtime, map_name as bootstrap_map
    from community_maps import BY_ID, custom_definitions
    definitions = {**BY_ID, **custom_definitions(package.get('map_definitions', {})),
                   **custom_definitions(prepared.get('custom_maps', {}))}
    bootstrap_contract = package.get('client_bootstrap_contract')
    bootstrap_id = 'Drydock' if args.public_session else args.expected_map
    selected_bootstrap = bootstrap_map(bootstrap_contract, bootstrap_id, definitions=definitions)
    template = bootstrap_runtime((ROOT / 'lua/client.lua').read_text(encoding='utf-8'), bootstrap_contract,
                                 bootstrap_id, definitions=definitions)
    map_definitions = write_map_definitions(ROOT, run, definitions, definitions.get(args.expected_map),
                                            package, public=args.public_session,
                                            objectives=prepared.get('map_objectives'),
                                            minimap=prepared.get('map_minimap'))
    diagnostic_profile = bool(args.headless or args.test_source or args.seconds is not None)
    with ProfileSession(mode=MODE, workspaces=(workspace, source.parent / 'TRIBES3 Client Sessions'),
                        diagnostic=diagnostic_profile, source_game=source, package_root=ROOT,
                        bootstrap_map=selected_bootstrap) as player_profile, ExitStack() as audio:
        print('Joining TRIBES 3 Community Server at ' + destination, flush=True)
        print('Session: ' + str(run), flush=True)
        print('CLIENT_PREPARATION_CONSUMED|fileCopyBytes=0|bulkHashBytes=0', flush=True)
        binary=game/REL
        exe=binary/'TribesRivals.exe'
        profile = player_profile.directory(run)
        argv = [str(exe), 'Topaz', '-RallyHereEnv=Retail', '-EpicApp=TribesGameClientLive',
                '-storefront=Steam', '-NoEAC', '-NoEACLogin', '-offline',
                '-abslog=' + str(run / 'game.log'), '-UserDir=' + str(profile), '-nobots',
                '-httpproxy=127.0.0.1:1', '-DefaultPlatformService=NULL', '-nosteam',
                '-noSteamV2', '-noeos', '-Port=0', '-REAResearchScope=' + uuid.uuid4().hex]
        if args.test_source:
            argv.append('-MULTIHOME=' + args.test_source)
        argv += renderer_arguments(headless=args.headless, fullscreen=player_profile.fullscreen_default,
                                   test_render_profile=args.test_render_profile)
        cloud_map = args.expected_map if not args.headless and args.expected_map in STOCK_CLOUD_MAPS else ''
        if args.spectate and (any(not (ROOT/name).is_file()for name in ('lua/spectator_client.lua','lua/spectator_materials.lua'))
                or any('@@' + tag + '@@' not in template for tag in
                       ('SPECTATOR_ROLE', 'SPECTATOR_RUNTIME', 'SPECTATOR_MATERIAL_RUNTIME', 'MATCH_LEASE', 'WATCH_ID'))):
            raise ValueError('The spectator runtime is incomplete. Update the community client.')
        if '@@DAMNATION_WATER@@' in template:
            water_runtime = ROOT / 'lua/damnation_water.lua'
            if not water_runtime.is_file():
                raise ValueError('The Damnation water runtime is incomplete. Update the community client.')
            template = template.replace('@@DAMNATION_WATER@@', json.dumps(water_runtime.as_posix(), ensure_ascii=False))
        template = template.replace('@@SHOW_FLAG_INDICATORS@@', 'true' if args.show_flag_indicators else 'false')
        template = template.replace('@@STOCK_CLOUD_MAP@@', json.dumps(cloud_map))
        settings_path = profile / 'Saved/Config/Windows/GameUserSettings.ini'
        template = template.replace('@@MUSIC_SETTINGS@@', json.dumps(settings_path.as_posix(), ensure_ascii=False))
        if '@@MAP_SOUNDTRACK@@' in template:
            soundtrack = 'nil'
            soundtrack_player = _SIGNED_SOUNDTRACK_PLAYER
            if soundtrack_player is None and any(row['path'] == 'map_soundtracks.py' for row in package['files']):
                from map_soundtracks import soundtrack_player
            if soundtrack_player is not None:
                routes = audio.enter_context(soundtrack_player(
                    ROOT, run, package, enabled=not (args.headless or args.spectate or args.test_render_profile),
                    workspace=workspace))
                if routes:
                    keys = ','.join(f'[{json.dumps(name)}]=true' for name in routes)
                    session = json.dumps(run.as_posix(), ensure_ascii=False)
                    soundtrack = f'{{directory={session},routes={{{keys}}}}}'
            template = template.replace('@@MAP_SOUNDTRACK@@', soundtrack)
        weather_module = weather_runtime_path(ROOT, run, package)
        template = template.replace('@@MISSION_PERIMETER_COLLISION@@',
                                    json.dumps((ROOT/'lua/mission_perimeter_collision.lua').as_posix(), ensure_ascii=False))
        for key, value in dict(EXPECTED=engine_command_line(argv[2:]), OUTPUT=(run / 'events.txt').as_posix(), DESTINATION=destination, FLAG_MARKERS=(ROOT / 'lua/flag_markers.lua').as_posix(), FLAG_PROJECTION=(ROOT / 'lua/flag_projection.lua').as_posix(), JETPACK_INPUT=(ROOT / 'lua/jetpack_input.lua').as_posix(), GEOMETRY=(ROOT/'lua/geometry_runtime.lua').as_posix(), LEVEL_SETTINGS=(ROOT/'lua/level_settings.lua').as_posix(), MAP_DEFINITIONS=map_definitions.as_posix(), SNOWBLIND_WEATHER=weather_module.as_posix(), SPECTATOR_ROLE='spectator' if args.spectate else 'player', SPECTATOR_RUNTIME=(ROOT/'lua/spectator_client.lua').as_posix(), SPECTATOR_MATERIAL_RUNTIME=(ROOT/'lua/spectator_materials.lua').as_posix(), MATCH_LEASE=args.match_id or '', WATCH_ID=args.watch_id or '').items():
            template = template.replace('@@' + key + '@@', json.dumps(value, ensure_ascii=False))
        if '@@' in template:
            raise RuntimeError('Incomplete client runtime template.')
        mod = binary / 'ue4ss/Mods/CommunityLauncher/Scripts/main.lua'
        mod.parent.mkdir(parents=True)
        mod.write_text(template, encoding='utf-8')
        (mod.parents[2] / 'mods.txt').write_text('CommunityLauncher : 1\n', encoding='utf-8')
        save(run / 'session.json', dict(build=package['build_id'], capability='join-only',
                                       role='spectator' if args.spectate else 'player', match_id=args.match_id, watch_id=args.watch_id,
                                       destination=destination, source=str(source), verification=verification,
                                       argv=argv, private_executable_sha256=private_executable_sha256))
        startup_progress('launching_game')
        stopped = threading.Event()
        def monitor():
            path = run / 'events.txt'
            while not stopped.wait(1):
                try:
                    if not path.is_file():
                        continue
                    data = path.read_text(errors='replace') if path.stat().st_size <= 1048576 else 'RUNTIME_ERROR|Output bound'
                    if runtime_failure(data.splitlines()):
                        if not (run / 'cancel.json').exists():
                            save(run / 'cancel.json', dict(cancel=True, reason='Client adapter stopped; see events.txt'))
                        return
                except OSError:
                    continue
        watcher = threading.Thread(target=monitor, daemon=True)
        watcher.start()
        from owned_native_session import run_owned_job
        try:
            player_profile.starting_native()
            result = run_owned_job(argv, game, dict(os.environ, SteamAppId='2687970', SteamGameId='2687970'), run / 'execution', budget=args.seconds, cancellation_path=run / 'cancel.json')
            player_profile.confirm_cleanup(result)
        finally:
            stopped.set()
            watcher.join(timeout=2)
        print('Client session ended: ' + result['status'], flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print('Unable to join: ' + str(exc), file=sys.stderr)
        sys.exit(1)
