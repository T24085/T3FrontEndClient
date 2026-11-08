"""Linux-only Steam command handoff; fake Proton proves argv handling, not game compatibility."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

if sys.platform == 'linux':
    from linux_launcher import main, merge_dll_overrides, prepare_launch, run_in_terminal, setup_option, steam_command, windows_path


@unittest.skipUnless(sys.platform == 'linux', 'POSIX path and Steam wrapper checks run on Linux')
class LinuxLauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tribes linux space ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root/'Community Client'
        for name in ('python/pythonw.exe', 'linux_bootstrap.pyw', 'package-manifest.json'):
            file = self.package/name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'fixture')
        self.game = self.root/'Steam Library/TRIBES 3'
        for name in ('Topaz/Binaries/Win64/TribesRivals.exe', 'TribesRivals.exe'):
            file = self.game/name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'not executable test data')
        self.proton = self.root/'Proton Tool/proton'
        self.proton.parent.mkdir()
        self.proton.write_text('#!/usr/bin/python3\nimport json,os,sys\n'
                               'if sys.argv[1]=="getcompatpath": print("Z:\\\\\")\n'
                               'else: open(os.environ["TRIBES_TEST_CAPTURE"],"w").write(json.dumps(sys.argv[1:]))\n')
        self.proton.chmod(0o755)
        self.command = [str(self.proton), 'waitforexitandrun', str(self.game/'TribesRivals.exe'), '-original-argument']
        self.env = dict(os.environ, SteamAppId='2687970', SteamGameId='2687970',
                        STEAM_COMPAT_DATA_PATH=str(self.root/'compatdata/2687970'),
                        STEAM_COMPAT_INSTALL_PATH=str(self.game), XDG_DATA_HOME=str(self.root/'User Data'),
                        TRIBES_TEST_CAPTURE=str(self.root/'captured.json'))

    def test_actual_subprocess_handoff_and_certificate_snapshot(self):
        with patch('linux_launcher.ROOT', self.package), patch.dict(os.environ, self.env, clear=True), \
                patch.object(sys, 'argv', ['linux_launcher.py', '--steam-launch', *self.command]):
            self.assertEqual(main(), 0)
        captured = json.loads((self.root/'captured.json').read_text())
        self.assertEqual(captured[0], 'waitforexitandrun')
        self.assertEqual(captured[1], windows_path('Z:\\', self.package/'python/pythonw.exe'))
        self.assertIn(windows_path('Z:\\', self.game), captured)
        self.assertNotIn('-original-argument', captured)
        sessions = list((self.root/'User Data/Tribes3CommunityStarter/linux-launches').iterdir())
        self.assertEqual(len(sessions), 1)
        self.assertTrue((sessions[0]/'ca-bundle.pem').is_file())
        self.assertEqual((sessions[0]/'ca-bundle.pem').stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((sessions[0]/'launch.json').read_text())['game_source'], str(self.game))

    def test_steam_outer_separator_keeps_nested_separators(self):
        command = ['/Steam/reaper', 'SteamLaunch', 'AppId=2687970', '--',
                   '/Steam Runtime/_v2-entry-point', '--verb=waitforexitandrun', '--', *self.command]
        argv = ['linux_launcher.py', '--steam-launch', '--', *command]
        with patch('linux_launcher.ROOT', self.package), patch.object(sys, 'argv', argv), \
                patch('linux_launcher.prepare_launch', return_value=(command, self.env, self.package)) as prepare, \
                patch('linux_launcher.run_in_terminal', return_value=0):
            self.assertEqual(main(), 0)
        prepare.assert_called_once_with(self.package, command, os.environ)

    def test_runtime_prefix_and_selected_proton_are_preserved(self):
        command = ['/Steam Runtime/_v2-entry-point', '--verb=waitforexitandrun', '--', *self.command]
        calls = []
        def translator(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout=b'Z:\\\r\n', stderr=b'')
        argv, env, _ = prepare_launch(self.package, command, self.env, run=translator)
        self.assertEqual(calls[0], command[:4]+['getcompatpath', '/'])
        self.assertEqual(argv[:5], command[:5])
        self.assertEqual(env['WINEDLLOVERRIDES'], 'dwmapi=n,b')

    def test_rejects_wrong_app_ambiguous_proton_and_foreign_install(self):
        for env, command in ((dict(self.env, SteamAppId='1'), self.command),
                             (dict(self.env, STEAM_COMPAT_DATA_PATH='relative'), self.command),
                             (self.env, [*self.command, str(self.proton)]),
                             (self.env, [str(self.proton), 'destroyprefix', *self.command[2:]]),
                             (dict(self.env, STEAM_COMPAT_INSTALL_PATH='/'), self.command)):
            with self.subTest(command=command), self.assertRaises(ValueError): steam_command(command, env)

    def test_path_mapping_failure_and_missing_payload_never_launch(self):
        for result in (subprocess.CompletedProcess([], 1, b'', b'error'),
                       subprocess.CompletedProcess([], 0, b'not-a-root', b'')):
            with self.assertRaises(ValueError):
                prepare_launch(self.package, self.command, self.env, run=lambda *a, **k: result)
        (self.package/'python/pythonw.exe').unlink()
        with self.assertRaises(ValueError): prepare_launch(self.package, self.command, self.env)

    def test_setup_quotes_paths_without_shell_substitution_and_merges_overrides(self):
        path = self.root/"folder ' with $ and ; chars"
        parsed = shlex.split(setup_option(path))
        self.assertEqual(parsed, [str(path/'Start Community Starter.sh'), '--steam-launch', '%command%'])
        self.assertEqual(merge_dll_overrides('dxgi=b;dwmapi.dll,other=b;dinput8=n'),
                         'dxgi=b;other=b;dinput8=n;dwmapi=n,b')
        for root in ('relative', 'Z:\\folder', '\\\\server\\share\\'):
            with self.assertRaises(ValueError): windows_path(root, self.package)

    def test_failed_log_does_not_discard_the_running_child_owner(self):
        marker = self.root/'child-terminal.txt'
        program = ('import sys,time;from pathlib import Path;'
                   'print("output",flush=True);time.sleep(.15);Path(sys.argv[1]).write_text("finished")')
        class FullLog:
            def write(self, data): raise OSError('Simulated full logging disk')
        with self.assertRaisesRegex(OSError, 'after the client finished'):
            run_in_terminal([sys.executable, '-B', '-c', program, str(marker)], self.env, self.root, FullLog())
        self.assertEqual(marker.read_text(), 'finished')


if __name__ == '__main__':
    unittest.main(verbosity=2)
