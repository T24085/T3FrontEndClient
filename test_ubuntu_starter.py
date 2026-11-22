"""Verify the native Starter does not run Steam during startup."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ubuntu_join_worker import serve, status

if sys.platform == 'linux':
    from ubuntu_starter import APP_ID, HANDOFF_WAIT, MARKER, SNAP_LOCK, GameHandoff, dispatch, main, steam_persona
    from ubuntu_startup import StarterBusy, exclusive


class UbuntuJoinWorkerTest(unittest.TestCase):
    def join(self, sync, caps, *, session=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root/'joins'/'fixture'
            directory.mkdir(parents=True)
            workspace = root/'game-files'
            request = {
                'connection': {}, 'issued': time.time(), 'code': 'TEST', 'token': 'fixture',
                'player': 'player', 'role': 'player', 'map': 'Stonehenge2026', 'match': 'match',
            }
            if session is not None:
                request['direct_session'] = session
            (directory/'claimed.json').write_text(json.dumps(request), encoding='utf-8')
            observed = []

            class Lobby:
                def __init__(self, *_args, **_kwargs):
                    self.lock = threading.RLock()
                    self.direct_session = 'a'*32
                    self.close = Mock()

                def capabilities(self):
                    observed.append(self.direct_session)
                    return caps

                def begin_game_attempt(self):
                    self.direct_session = 'b'*32

            def start(**_kwargs):
                lobby = direct.DirectGame.call_args.args[0]
                lobby.begin_game_attempt()
                observed.append(lobby.direct_session)

            game = SimpleNamespace(start=Mock(side_effect=start), snapshot=lambda: {'status': 'finished'},
                                   thread=None, stop=Mock())
            direct = SimpleNamespace(DirectClient=Lobby, DirectGame=Mock(return_value=game))
            with patch.dict(sys.modules, direct_client=direct, map_sync=SimpleNamespace(MapSync=lambda *a: sync)):
                self.assertEqual(serve(directory, root, root, workspace, None), 0)
            lobby = direct.DirectGame.call_args.args[0]
            direct.DirectGame.assert_called_once_with(lobby, root, root, workspace,
                                                    workspace/'direct-desktop-control', map_sync=sync)
            game.start.assert_called_once_with(expected_map='Stonehenge2026', expected_match_id='match')
            self.assertEqual(json.loads((directory/'status.json').read_bytes())['status'], 'finished')
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


@unittest.skipUnless(sys.platform == 'linux', 'Native Ubuntu tests run on Linux')
class UbuntuHandoffTest(unittest.TestCase):
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

    def test_ordinary_steam_play_preserves_its_command(self):
        command = ['steam-runtime','proton','run','ordinary-game.exe','-argument']
        with patch('ubuntu_starter.os.execvp',side_effect=OSError) as execute, self.assertRaises(OSError):
            dispatch(command)
        execute.assert_called_once_with(command[0],command)

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
