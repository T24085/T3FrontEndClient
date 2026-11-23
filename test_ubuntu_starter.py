"""Verify the native Starter does not run Steam during startup."""
from pathlib import Path
from hashlib import sha256
import json
import os
import runpy
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, sentinel

from ubuntu_join_worker import SWITCH_FILE, SWITCH_RESULT, serve, status, switch_public_team

DIRECT_SOURCE = Path(__file__).resolve().parent/'experimental/direct-hosting/src'

if sys.platform == 'linux':
    from ubuntu_starter import APP_ID, HANDOFF_WAIT, MARKER, SNAP_LOCK, GameHandoff, dispatch, main, steam_persona
    from ubuntu_startup import StarterBusy, exclusive


class UbuntuJoinWorkerTest(unittest.TestCase):
    def test_deferred_first_launch_import_checks_saved_profile(self):
        from base64 import b64encode
        from ubuntu_join_worker import IMPORT_FILE, IMPORT_RESULT, apply_retail_import

        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(sys, 'path', [str(DIRECT_SOURCE), *sys.path]):
            state = Path(temporary)
            worker = state/'join'
            worker.mkdir()
            retail = b'[/Script/Valhalla.ValPlayerInput]\nSavedSettingsConfig=(Sensitivity=0.8)\n'
            files = {'Input.ini': b64encode(retail).decode('ascii')}
            failure = ValueError('Your community settings are already in use.')
            for first_launch in (True, False):
                data = {'firstLaunch': True, 'files': files} if first_launch else files
                (state/IMPORT_FILE).write_text(json.dumps(data), encoding='utf-8')
                with patch('player_profile.import_retail_settings',
                           side_effect=failure if first_launch else None, return_value=('Input.ini',)) as importer:
                    apply_retail_import(state, worker)
                self.assertEqual(importer.call_args.kwargs['first_launch'], first_launch)
                self.assertFalse((state/IMPORT_FILE).exists())
                result = json.loads((state/IMPORT_RESULT).read_bytes())['message']
                self.assertIn('already in use' if first_launch else 'imported.', result)

    def join(self, sync, caps, *, session=None, through_bridge=False, spectator=False,
             public=False, team=None, switch=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root/'joins'/'fixture'
            directory.mkdir(parents=True)
            workspace = root/'game files'
            game_dir = root/'Steam Library' if through_bridge else root
            package = root
            request = {
                'connection': {}, 'issued': time.time(), 'code': 'TEST', 'token': 'fixture',
                'player': 'player', 'role': 'player', 'map': 'Stonehenge2026', 'match': 'match',
            }
            if session is not None:
                request['direct_session'] = session
            watch_id, watch_token = 'fixture-watch-id', 'T' * 32
            if spectator:
                request.update(role='spectator', watch_id=watch_id, watch_token=watch_token)
            if public:
                request.update(role='public', name='Pilot')
                if team is not None:
                    request['team'] = team
            (directory/'claimed.json').write_text(json.dumps(request), encoding='utf-8')
            observed = []
            switched = threading.Event()
            nonce = 'f'*32
            if switch:
                (directory/SWITCH_FILE).write_text(json.dumps({'nonce': nonce, 'round': 2, 'team': 'blue'}),
                                                   encoding='utf-8')

            class Lobby:
                def __init__(self, *_args, **_kwargs):
                    self.lock = threading.RLock()
                    self._watch_tokens = {}
                    self.direct_session = 'a'*32
                    self.close = Mock()

                def capabilities(self):
                    observed.append(self.direct_session)
                    return caps

                def begin_game_attempt(self):
                    self.direct_session = 'b'*32

                def public_state(self, *, renew):
                    return {}

            def start(**_kwargs):
                lobby = direct.DirectGame.call_args.args[0]
                lobby.begin_game_attempt()
                observed.append(lobby.direct_session)

            def snapshot():
                if not switch or (directory/SWITCH_RESULT).exists():
                    return {'status': 'finished'}
                return {'status': 'stopped' if switched.is_set() else 'playing'}

            game = SimpleNamespace(start=Mock(side_effect=start), snapshot=snapshot, public_round=None,
                                   thread=None, stop=Mock())

            def change_team(round_id, target):
                switched.set()
                status_path = directory/'status.json'
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    if status_path.exists() and json.loads(status_path.read_bytes()).get('progress') == 'Switching Public CTF teams…':
                        return 'starting'
                    time.sleep(.03)
                raise ValueError('The starting phase was not shown during the switch.')

            game.switch_public_team = Mock(side_effect=change_team)
            def spectate(value):
                self.assertEqual(value, watch_id)
                lobby = direct.DirectGame.call_args.args[0]
                self.assertEqual(lobby._watch_tokens.pop(watch_id), watch_token)
                start()
            game.start_spectating = Mock(side_effect=spectate)
            game.stop_spectating = Mock()
            game.start_public = Mock(side_effect=lambda *args, **kwargs: start())
            direct = SimpleNamespace(DirectClient=Lobby, DirectGame=Mock(return_value=game))
            map_sync = Mock(return_value=sync)
            with patch.object(sys, 'path', [str(DIRECT_SOURCE), *sys.path]), \
                    patch.dict(sys.modules, direct_client=direct, map_sync=SimpleNamespace(MapSync=map_sync)):
                if through_bridge:
                    bridge = Path(__file__).with_name('linux_bootstrap.pyw')
                    package = bridge.resolve().parent
                    main = runpy.run_path(str(bridge))['main']
                    launch_dir = root/'launch'
                    launch_dir.mkdir()
                    ca = b'fixture certificate'
                    (launch_dir/'ca-bundle.pem').write_bytes(ca)
                    args = [str(bridge), '--game-dir', str(game_dir), '--workspace', str(workspace),
                            '--launch-dir', str(launch_dir), '--ca-sha256', sha256(ca).hexdigest(),
                            '--ubuntu-join', str(directory)]
                    context = SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_REQUIRED)
                    with patch.object(sys, 'argv', args), patch.dict(os.environ), \
                            patch.object(ssl, 'create_default_context', return_value=context), \
                            patch.dict(main.__globals__, check_proton=Mock(return_value='fixture'),
                                       check_owned_jobs=Mock()):
                        self.assertEqual(main(), 0, (launch_dir/'bridge.log').read_text(encoding='utf-8'))
                else:
                    self.assertEqual(serve(directory, package, game_dir, workspace, None), 0)
            lobby = direct.DirectGame.call_args.args[0]
            map_sync.assert_called_once_with(lobby, package, workspace)
            direct.DirectGame.assert_called_once_with(lobby, package, game_dir, workspace,
                                                    workspace/'direct-desktop-control', map_sync=sync)
            outcome = json.loads((directory/'status.json').read_bytes())
            if spectator:
                game.start_spectating.assert_called_once_with(watch_id)
                game.start.assert_not_called()
                self.assertTrue(outcome['watch_released'])
            elif public:
                if team is None or team == 'auto':
                    game.start_public.assert_called_once_with('Pilot')
                else:
                    game.start_public.assert_called_once_with('Pilot', team=team)
                game.start.assert_not_called()
                game.start_spectating.assert_not_called()
            else:
                game.start.assert_called_once_with(expected_map='Stonehenge2026', expected_match_id='match')
            self.assertEqual(outcome['status'], 'finished')
            if switch:
                game.switch_public_team.assert_called_once_with(2, 'blue')
                self.assertEqual(json.loads((directory/SWITCH_RESULT).read_bytes()),
                                 {'nonce': nonce, 'status': 'starting'})
            lobby.close.assert_called_once()
            return observed

    def test_proton_handoff_enables_the_advertised_per_match_sync(self):
        sync = SimpleNamespace(session_enabled=False, start=Mock(), cancelled=threading.Event())
        self.join(sync, {'mapFileSync': 2, 'mapSessionSync': 3})
        sync.start.assert_called_once_with(2, session_version=3)

    def test_worker_keeps_the_legacy_client_signature(self):
        sync = SimpleNamespace(start=Mock(), cancelled=threading.Event())
        self.join(sync, {'mapFileSync': 2, 'mapSessionSync': 3})
        sync.start.assert_called_once_with(2)

    def test_worker_keeps_the_gui_admission_through_game_start(self):
        sync = SimpleNamespace(session_enabled=False, start=Mock(), cancelled=threading.Event())
        session = 'c'*32
        observed = self.join(sync, {'mapFileSync': 2, 'mapSessionSync': 3}, session=session)
        self.assertEqual(observed, [session, session])

    def test_proton_bridge_passes_cli_paths_to_the_join_worker(self):
        sync = SimpleNamespace(session_enabled=False, start=Mock(), cancelled=threading.Event())
        self.join(sync, {'mapFileSync': 2, 'mapSessionSync': 3}, through_bridge=True)

    def test_proton_worker_preserves_public_team_or_defaults_to_auto(self):
        for team in ('blue', 'red', 'auto', None):
            with self.subTest(team=team):
                sync = SimpleNamespace(session_enabled=False, start=Mock(), cancelled=threading.Event())
                session = 'c'*32
                observed = self.join(sync, {'mapFileSync': 2, 'mapSessionSync': 3},
                                     through_bridge=True, session=session, public=True, team=team)
                self.assertEqual(observed, [session, session])

    def test_proton_worker_uses_reserved_spectator_grant_and_session(self):
        session = 'c' * 32
        sync = SimpleNamespace(session_enabled=False, start=Mock(), cancelled=threading.Event())
        observed = self.join(sync, {'mapFileSync': 2, 'mapSessionSync': 3}, session=session,
                             through_bridge=True, spectator=True)
        self.assertEqual(observed, [session, session])

    def test_proton_worker_keeps_ownership_during_the_team_switch(self):
        sync = SimpleNamespace(start=Mock(), cancelled=threading.Event())
        self.join(sync, {}, public=True, switch=True)


@unittest.skipUnless(sys.platform == 'linux', 'Native Ubuntu tests run on Linux')
class UbuntuHandoffTest(unittest.TestCase):
    def test_native_offer_skips_active_game_and_existing_community_settings(self):
        from ubuntu_starter import linux_game_running, ubuntu_retail_import_offer

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            local = home/'retail/AppData/Local'
            retail = local/'Topaz/Saved/Config/Windows'
            retail.mkdir(parents=True)
            (retail/'Input.ini').write_text(
                '[/Script/Valhalla.ValPlayerInput]\nSavedSettingsConfig=(Sensitivity=0.8)\n',
                encoding='utf-8')
            state = home/'starter'
            process = home/'proc/42'
            process.mkdir(parents=True)
            (process/'comm').write_bytes(b'TribesRivals.ex\n')
            self.assertTrue(linux_game_running(home/'proc'))
            with patch('ubuntu_starter.retail_profiles', return_value=[retail]), \
                    patch('ubuntu_starter.linux_game_running', return_value=True) as game_running:
                self.assertIsNone(ubuntu_retail_import_offer(None, home, state))
                game_running.return_value = False
                self.assertEqual(ubuntu_retail_import_offer(None, home, state)[0], retail)
                config = (state/'compatdata/pfx/drive_c/users/steamuser/AppData/Local'
                          /'Tribes3CommunityStarter/player-settings/profile/Saved/Config/Windows')
                config.mkdir(parents=True)
                (config/'Input.ini').write_text('[Community]\nSaved=1\n', encoding='utf-8')
                self.assertIsNone(ubuntu_retail_import_offer(None, home, state))

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.state = Path(self.home.name)/'ClanWarsUbuntuStarter'
        self.state.mkdir(mode=0o700)
        self.lobby = SimpleNamespace(lock=threading.RLock(),connection={'access_token':'fixture'},
                                     code='TEST',token='fixture',player_id='player',direct_session='a'*32)
        self.lobby.begin_game_attempt = lambda: setattr(self.lobby, 'direct_session', 'b'*32)

    def test_native_probe_never_calls_steam(self):
        fixture = SimpleNamespace(capabilities=lambda:{'publicCTF':True},live_matches=lambda:[],
                                  close=lambda:None,server_maps={'Test':{}})
        direct = SimpleNamespace(DirectClient=lambda *a:fixture,group_connection=lambda *a:{})
        with patch.dict(sys.modules, direct_client=direct),                 patch.dict(os.environ, XDG_DATA_HOME=str(self.state.parent)),                 patch('ubuntu_starter.subprocess.Popen') as launch:
            self.assertEqual(main(['--check-lobby']),0)
            launch.assert_not_called()

    def test_native_directory_uses_selected_host_and_closes_previous_lobby(self):
        original, selected = Mock(), Mock()
        direct = SimpleNamespace(DirectClient=Mock(side_effect=[original, selected]),
                                 group_connection=Mock(return_value={'hostname': 'bundled'}),
                                 load_server_directory=Mock(return_value=sentinel.directory))

        def show(lobby, state, on_ready, *, directory):
            self.assertEqual(state, self.state)
            self.assertIs(directory, sentinel.directory)
            if lobby is original:
                on_ready()
                return {'hostname': 'selected'}
            original.close.assert_called_once()
            self.assertIsNone(on_ready)
            return None

        ready = Mock()
        with patch.dict(sys.modules, direct_client=direct), \
                patch('ubuntu_starter.show_starter', side_effect=show), \
                patch('ubuntu_starter.subprocess.Popen') as launch:
            self.assertEqual(main([], owned_state=self.state, on_ready=ready), 0)
        launch.assert_not_called()
        ready.assert_called_once()
        selected.close.assert_called_once()
        direct.group_connection.assert_called_once()
        self.assertEqual([call.args[0]['hostname'] for call in direct.DirectClient.call_args_list],
                         ['bundled', 'selected'])

    def test_native_directory_opens_when_the_bundled_host_is_unavailable(self):
        chooser, lobby, ready = Mock(), Mock(), Mock()
        direct = SimpleNamespace(DirectClient=Mock(return_value=lobby),
                                 group_connection=Mock(side_effect=OSError('Unreachable')),
                                 load_server_directory=Mock(return_value=sentinel.directory),
                                 browse_for_server=Mock(return_value={'hostname': 'selected'}))

        def browse(_window, _directory, _state, *, on_ready):
            on_ready()
            return {'hostname': 'selected'}

        direct.browse_for_server.side_effect = browse
        with patch.dict(sys.modules, direct_client=direct, tkinter=SimpleNamespace(Tk=lambda: chooser)), \
                patch('ubuntu_starter.show_starter', return_value=None) as show:
            self.assertEqual(main([], owned_state=self.state, on_ready=ready), 0)
        direct.browse_for_server.assert_called_once_with(chooser, sentinel.directory, self.state, on_ready=ready)
        chooser.destroy.assert_called_once()
        show.assert_called_once_with(lobby, self.state, None, directory=sentinel.directory)
        ready.assert_called_once()

    def test_explicit_join_is_claimed_once_and_uses_separate_prefix(self):
        calls = []
        handoff = GameHandoff(self.lobby,self.state,launch=lambda argv,**_:calls.append(argv))
        self.assertEqual(handoff.snapshot()['status'],'idle')
        self.assertFalse(calls)
        with patch('ubuntu_starter.shutil.which',return_value='/usr/bin/steam'):
            self.assertEqual(handoff.start(expected_map='Stonehenge2026',expected_match_id='match'),'starting')
        request = handoff.directory
        self.assertEqual((request/'request.json').stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads((request/'request.json').read_bytes())['direct_session'], self.lobby.direct_session)
        self.assertEqual(self.lobby.direct_session, 'b'*32)
        argv = ['proton', 'run', 'original.exe', calls[0][-1]]
        self.assertEqual(calls[0][:3],['/usr/bin/steam','-applaunch',APP_ID])
        self.assertTrue(calls[0][-1].startswith(MARKER))

        def launch(_root, full, env, **kwargs):
            self.assertEqual(full,argv[:-1])
            self.assertTrue((request/'claimed.json').is_file())
            self.assertEqual(env['STEAM_COMPAT_DATA_PATH'],str(self.state/'compatdata'))
            self.assertEqual(kwargs['workspace'],self.state/'game-files')
            self.assertEqual(kwargs['join_directory'], request)
            return ['proton','run','--launch-dir','Z:\\dummy','--ubuntu-join','S:\\request'],env,None

        def run(command, *_):
            self.assertEqual(command[-2:], ['--ubuntu-join', 'S:\\request'])
            status(request,'finished')
            return 0

        with patch.dict(os.environ, XDG_DATA_HOME=str(self.state.parent)),                 patch('ubuntu_starter.prepare_launch',side_effect=launch) as prep,                 patch('ubuntu_starter.run_in_terminal',side_effect=run):
            self.assertEqual(dispatch(argv),0)
            with self.assertRaisesRegex(ValueError,'expired'):
                dispatch(argv)
            prep.assert_called_once()
        self.assertEqual(handoff.snapshot()['status'],'finished')
        self.assertFalse((request/'claimed.json').exists())

    def test_public_team_passes_through_the_native_steam_handoff(self):
        for team in ('blue', 'red', 'auto'):
            with self.subTest(team=team):
                launch = Mock()
                handoff = GameHandoff(self.lobby, self.state, launch=launch)
                with patch('ubuntu_starter.shutil.which', return_value='/usr/bin/steam'):
                    self.assertEqual(handoff.start_public('Pilot', team=team), 'starting')
                request = handoff.directory
                command = ['proton', 'run', 'original.exe', launch.call_args.args[0][-1]]

                def run(*_args):
                    details = json.loads((request/'claimed.json').read_bytes())
                    self.assertEqual((details['role'], details['name'], details['team']),
                                     ('public', 'Pilot', team))
                    self.assertEqual(details['direct_session'], self.lobby.direct_session)
                    status(request, 'finished')
                    return 0

                with patch.dict(os.environ, XDG_DATA_HOME=str(self.state.parent)), \
                        patch('ubuntu_starter.prepare_launch', return_value=([], {}, None)), \
                        patch('ubuntu_starter.run_in_terminal', side_effect=run):
                    self.assertEqual(dispatch(command), 0)
                self.assertEqual(handoff.snapshot()['status'], 'finished')

    def test_private_handoff_reports_the_owned_match_before_and_after_launch(self):
        handoff = GameHandoff(self.lobby, self.state, launch=Mock())
        with patch('ubuntu_starter.shutil.which', return_value='/usr/bin/steam'):
            handoff.start(expected_match_id='current')
        self.assertEqual(handoff.snapshot()['matchId'], 'current')
        status(handoff.directory, 'playing')
        playing = handoff.snapshot()
        self.assertEqual((playing['role'], playing['status'], playing['matchId']), ('player', 'playing', 'current'))
        handoff.stop()
        self.assertTrue((handoff.directory/'cancel').exists())
        self.assertEqual(handoff.snapshot()['status'], 'stopped')
        with patch('ubuntu_starter.shutil.which', return_value='/usr/bin/steam'):
            handoff.start_public('Pilot')
        self.assertIsNone(handoff.snapshot()['matchId'])

    def test_team_switch_uses_the_open_session_and_surfaces_a_denial(self):
        launch = Mock()
        handoff = GameHandoff(self.lobby, self.state, launch=launch)
        with patch('ubuntu_starter.shutil.which', return_value='/usr/bin/steam'):
            handoff.start_public('Pilot')
        directory = handoff.directory
        status(directory, 'playing')
        game = SimpleNamespace(switch_public_team=Mock(side_effect=ValueError('Team is full.')))
        with patch.object(sys, 'path', [str(DIRECT_SOURCE), *sys.path]), \
                patch('ubuntu_starter.time.sleep', side_effect=lambda _: switch_public_team(directory, game)):
            with self.assertRaisesRegex(RuntimeError, 'Team is full'):
                handoff.switch_public_team(4, 'red')
        game.switch_public_team.assert_called_once_with(4, 'red')
        launch.assert_called_once()
        self.assertEqual(handoff.snapshot()['status'], 'playing')

    def test_ordinary_steam_play_preserves_its_command(self):
        command = ['steam-runtime','proton','run','ordinary-game.exe','-argument']
        with patch('ubuntu_starter.os.execvp',side_effect=OSError) as execute, self.assertRaises(OSError):
            dispatch(command)
        execute.assert_called_once_with(command[0],command)

    def test_spectator_handoff_retains_the_admission_and_releases_a_cancelled_request(self):
        watch_id, watch_token = 'fixture-watch-id', 'T' * 32
        self.lobby._watch_tokens = {watch_id: watch_token}
        self.lobby.release_spectator = Mock()
        launch = Mock()
        handoff = GameHandoff(self.lobby, self.state, launch=launch)
        with patch('ubuntu_starter.shutil.which', return_value='/usr/bin/steam'):
            self.assertEqual(handoff.start_spectating(watch_id), 'starting')
        request = json.loads((handoff.directory/'request.json').read_bytes())
        self.assertEqual((request['watch_id'], request['watch_token']), (watch_id, watch_token))
        self.assertEqual(request['direct_session'], 'a' * 32)
        self.assertNotIn(watch_token, launch.call_args.args[0])
        handoff.stop_spectating()
        self.assertFalse((handoff.directory/'request.json').exists())
        self.lobby.release_spectator.assert_called_once_with(watch_id)

    def test_snap_dispatch_finds_the_host_request_after_shaders_and_shares_its_game_lock(self):
        home = Path(self.home.name)
        common = home/'snap/steam/common'
        calls = []
        handoff = GameHandoff(self.lobby, self.state, launch=lambda argv, **_: calls.append(argv))
        with patch('ubuntu_starter.shutil.which', return_value='/snap/bin/steam'), patch.dict(os.environ, HOME=str(home)):
            self.assertEqual(handoff.start(expected_match_id='match'), 'starting')
        request = handoff.directory
        snap_state = common/'.local/share/ClanWarsUbuntuStarter'
        self.assertEqual(request.parent, snap_state/'joins')
        self.assertTrue((snap_state/SNAP_LOCK).samefile(self.state/'steam-session.lock'))
        stamp = time.time() - 240
        os.utime(request/'request.json', (stamp, stamp))
        self.assertGreater(HANDOFF_WAIT, 240)
        argv = ['proton', 'run', 'original.exe', calls[0][-1]]

        def launch(_root, full, env, **kwargs):
            self.assertEqual(full, argv[:-1])
            self.assertEqual(kwargs['workspace'], snap_state/'game-files')
            self.assertEqual(kwargs['join_directory'], request)
            self.assertEqual(env['STEAM_COMPAT_DATA_PATH'], str(snap_state/'compatdata'))
            self.assertGreater((request/'claimed.json').stat().st_mtime, stamp + 200)
            return ['proton','run','--launch-dir','Z:\\dummy','--ubuntu-join','S:\\request'], env, None

        def run(*_args):
            status(request, 'finished')
            return 0

        snap_env = {'SNAP_NAME': 'steam', 'SNAP_USER_COMMON': str(common),
                    'HOME': str(common/'revision'), 'XDG_DATA_HOME': str(common/'unrelated')}
        with patch.dict(os.environ, snap_env), patch('ubuntu_starter.prepare_launch', side_effect=launch), \
                patch('ubuntu_starter.run_in_terminal', side_effect=run):
            with exclusive(self.state/'steam-session.lock'), self.assertRaises(StarterBusy):
                dispatch(argv)
            self.assertTrue((request/'request.json').is_file())
            self.assertEqual(dispatch(argv), 0)
        self.assertEqual(handoff.snapshot()['status'], 'finished')

    def test_snap_and_native_personas_select_the_selected_steam_install(self):
        home = Path(self.home.name)
        native = home/'.steam/root/config'
        snap = home/'snap/steam/common/.local/share/Steam/config'
        def vdf(folder, name, recent='1'):
            folder.mkdir(parents=True, exist_ok=True)
            (folder/'loginusers.vdf').write_text(
                '"users"\n{\n"76561198000000001"\n{\n"PersonaName" "Previous"\n"MostRecent" "0"\n}\n'
                f'"76561198000000002"\n{{\n"PersonaName" "{name}"\n"MostRecent" "{recent}"\n}}\n}}\n',
                encoding='utf-8')
        vdf(native, 'Native Pilot')
        vdf(snap, r'Snap \"Pilot\" {CTF}')
        with patch.dict(os.environ, XDG_DATA_HOME=str(home/'xdg')):
            self.assertEqual(steam_persona('/usr/bin/steam', home), 'Native Pilot')
            self.assertEqual(steam_persona('/snap/bin/steam', home), 'Snap "Pilot" {CTF}')
            vdf(snap, 'Previous', recent='0')
            self.assertIsNone(steam_persona('/snap/bin/steam', home))

    def test_snap_persona_falls_back_to_the_single_account_in_an_alternate_config(self):
        home = Path(self.home.name)
        config = home/'snap/steam/current/.steam/root/config'
        config.mkdir(parents=True)
        (config/'loginusers.vdf').write_text(
            r'''
            // account data written by Steam
            "Users"
            {
                "76561198000000001" // account comment
                {
                    "PersonaName" "Pilot \"One\" {CTF}"
                    "Extra" { "Nested" "value" }
                }
            }
            ''', encoding='utf-8-sig')
        self.assertEqual(steam_persona('/snap/bin/steam', home), 'Pilot "One" {CTF}')


if __name__ == '__main__':
    unittest.main()
