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
    from ubuntu_starter import APP_ID, MARKER, GameHandoff, dispatch, main


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
            return ['proton','run','--launch-dir','Z:\\dummy'],env,None

        def run(command, *_):
            self.assertIn('--ubuntu-join',command)
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


if __name__ == '__main__':
    unittest.main()
