"""Canonical packaged client entry, copied as client.py by candidate builders.

Prepared-client baseline: frozen Worldbuilding-20261102-r1/client.py,
SHA256 3baeb559c717aaad2316cdd2298e9c8e521cf373f87c358a398064dbaf8ce190.
Source manifest SHA256 740081ed79694c486fcff871b4e5ff3329100e5f7407eaf01985d3ed4c44a009.
"""
import argparse
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
    parser.add_argument('--match-id')
    parser.add_argument('--watch-id')
    parser.add_argument('--test-source', choices=ISOLATED_TEST_SOURCES, help=argparse.SUPPRESS)
    parser.add_argument('--game-dir')
    parser.add_argument('--workspace')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--rehash', action='store_true')
    parser.add_argument('--headless', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--seconds', type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()
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
        with startup.phase('package-verification'):package=verify_package()
        startup_progress('verifying_game')
        with startup.phase('original-verification'):
            manifest,identities,verification=verify_game(source,workspace,args.rehash)
        from map_catalog import verified_catalog
        map_overlay, custom_maps = None, None
        with startup.phase('map-verification'):
            if args.map_revision is None:
                catalog = verified_catalog(ROOT)
            else:
                from map_sync import load_overlay
                map_overlay, catalog, custom_maps = load_overlay(workspace, args.map_revision, package)
        if args.expected_map is not None and catalog.get(args.expected_map)!=args.expected_content_hash:
            raise ValueError('Your map files do not match this match. Update the community client.')
        if args.check:
            print(json.dumps(dict(build=package['build_id'],game=str(source),verification=verification,capability='join-only'),indent=2))
            return
        startup_progress('staging_game')
        with startup.phase('client-preparation'):
            descriptor=stage(ROOT,source,workspace,package,manifest,identities,verification,catalog=catalog,map_overlay=map_overlay,
                             custom_maps=custom_maps,
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
    from community_maps import BY_ID, custom_definitions, lua_map_definitions
    definitions = {**BY_ID, **custom_definitions(package.get('map_definitions', {})),
                   **custom_definitions(prepared.get('custom_maps', {}))}
    bootstrap_contract = package.get('client_bootstrap_contract')
    selected_bootstrap = bootstrap_map(bootstrap_contract, args.expected_map, definitions=definitions)
    template = bootstrap_runtime((ROOT / 'lua/client.lua').read_text(encoding='utf-8'), bootstrap_contract,
                                 args.expected_map, definitions=definitions)
    map_definitions = lua_map_definitions(ROOT, run, definitions.get(args.expected_map))
    diagnostic_profile = bool(args.headless or args.test_source or args.seconds is not None)
    with ProfileSession(mode=MODE, workspaces=(workspace, source.parent / 'TRIBES3 Client Sessions'),
                        diagnostic=diagnostic_profile, source_game=source, package_root=ROOT,
                        bootstrap_map=selected_bootstrap) as player_profile:
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
        argv += ['-nullrhi', '-nosound', '-unattended'] if args.headless else ['-d3d11'] + (['-fullscreen'] if player_profile.fullscreen_default else [])
        if not args.headless and args.expected_map in BY_ID and args.expected_map.endswith('2026'):
            # Trace clouds at half resolution and reconstruct at full resolution.
            argv.append('-ini:Engine:[SystemSettings]:r.VolumetricRenderTarget.Mode=1')
        if args.spectate and (any(not (ROOT/name).is_file()for name in ('lua/spectator_client.lua','lua/spectator_materials.lua'))
                or any('@@' + tag + '@@' not in template for tag in
                       ('SPECTATOR_ROLE', 'SPECTATOR_RUNTIME', 'SPECTATOR_MATERIAL_RUNTIME', 'MATCH_LEASE', 'WATCH_ID'))):
            raise ValueError('The spectator runtime is incomplete. Update the community client.')
        if '@@DAMNATION_WATER@@' in template:
            water_runtime = ROOT / 'lua/damnation_water.lua'
            if not water_runtime.is_file():
                raise ValueError('The Damnation water runtime is incomplete. Update the community client.')
            template = template.replace('@@DAMNATION_WATER@@', json.dumps(water_runtime.as_posix(), ensure_ascii=False))
        for key, value in dict(EXPECTED=engine_command_line(argv[2:]), OUTPUT=(run / 'events.txt').as_posix(), DESTINATION=destination, FLAG_MARKERS=(ROOT / 'lua/flag_markers.lua').as_posix(), FLAG_PROJECTION=(ROOT / 'lua/flag_projection.lua').as_posix(), JETPACK_INPUT=(ROOT / 'lua/jetpack_input.lua').as_posix(), GEOMETRY=(ROOT/'lua/geometry_runtime.lua').as_posix(), LEVEL_SETTINGS=(ROOT/'lua/level_settings.lua').as_posix(), MAP_DEFINITIONS=map_definitions.as_posix(), SNOWBLIND_WEATHER=(ROOT/'lua/snowblind_weather.lua').as_posix(), SPECTATOR_ROLE='spectator' if args.spectate else 'player', SPECTATOR_RUNTIME=(ROOT/'lua/spectator_client.lua').as_posix(), SPECTATOR_MATERIAL_RUNTIME=(ROOT/'lua/spectator_materials.lua').as_posix(), MATCH_LEASE=args.match_id or '', WATCH_ID=args.watch_id or '').items():
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
