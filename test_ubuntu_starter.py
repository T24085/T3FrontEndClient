"""Verify the native Starter does not run Steam during startup."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

if sys.platform == 'linux':
    from ubuntu_starter import APP_ID, MARKER, GameHandoff, dispatch, main
    from ubuntu_join_worker import status


@unittest.skipUnless(sys.platform == 'linux', 'Native Ubuntu tests run on Linux')
class UbuntuHandoffTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.state = Path(self.home.name)/'ClanWarsUbuntuStarter'
        self.state.mkdir(mode=0o700)
        self.lobby = SimpleNamespace(lock=threading.RLock(),connection={'access_token':'fixture'},
                                     code='TEST',token='fixture',player_id='player')

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
