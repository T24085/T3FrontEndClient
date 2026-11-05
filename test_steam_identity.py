import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from steam_identity import DLL_REL, PREFIX, SteamIdentityError, _read_native, read_steam_name


class SteamIdentityTest(unittest.TestCase):
    def test_local_account_persona_is_usable_without_steam_server_connection(self):
        class Function:
            def __init__(self,value):self.value=value;self.calls=0
            def __call__(self,*args):self.calls+=1;return self.value
        api=SimpleNamespace(**{name:Function(value) for name,value in {
            'SteamAPI_Init':True,'SteamAPI_Shutdown':None,'SteamAPI_SteamFriends_v017':2,
            'SteamAPI_SteamUser_v021':1,'SteamAPI_ISteamUser_BLoggedOn':False,
            'SteamAPI_ISteamUser_GetSteamID':76561198000000001,
            'SteamAPI_ISteamFriends_GetPersonaName':b'Cached pilot'}.items()})
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dll=root/DLL_REL;dll.parent.mkdir(parents=True);dll.write_bytes(b'fixture')
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'files':[{'path':DLL_REL,'bytes':7,'sha256':hashlib.sha256(b'fixture').hexdigest()}]}))
            with patch('steam_identity.ctypes.CDLL',return_value=api):
                self.assertEqual(_read_native(root,manifest),'Cached pilot')
                self.assertEqual(api.SteamAPI_ISteamUser_BLoggedOn.calls,0)
                api.SteamAPI_ISteamUser_GetSteamID.value=0
                with self.assertRaises(SteamIdentityError):_read_native(root,manifest)
            self.assertEqual(api.SteamAPI_Shutdown.calls,2)

    def test_changed_installed_api_is_rejected_before_loading_native_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);dll=root/DLL_REL;dll.parent.mkdir(parents=True);dll.write_bytes(b'changed')
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'files':[{
                'path':DLL_REL,'bytes':7,'sha256':hashlib.sha256(b'correct').hexdigest()}]}))
            with patch('steam_identity.ctypes.CDLL') as load:
                with self.assertRaises(SteamIdentityError): _read_native(root,manifest)
                load.assert_not_called()

    def test_helper_protocol_preserves_unicode_and_reports_logged_out_state(self):
        response=SimpleNamespace(returncode=0,stdout=PREFIX+json.dumps({'name':'Píløt 🚀'})+'\n',stderr='')
        with patch('steam_identity.subprocess.run',return_value=response) as run:
            self.assertEqual(read_steam_name('game','manifest'),'Píløt 🚀')
            self.assertEqual(run.call_args.kwargs['env']['SteamAppId'],'2687970')
            self.assertNotIn('SteamAPI_RestartAppIfNecessary',run.call_args.args[0])
        response=SimpleNamespace(returncode=1,stdout=PREFIX+json.dumps({'error':'Start Steam'})+'\n',stderr='')
        with patch('steam_identity.subprocess.run',return_value=response):
            with self.assertRaisesRegex(SteamIdentityError,'Start Steam'): read_steam_name('game','manifest')

    def test_timeout_is_bounded_and_no_name_is_invented(self):
        with patch('steam_identity.subprocess.run',side_effect=subprocess.TimeoutExpired('helper',12)):
            with self.assertRaisesRegex(SteamIdentityError,'timed out'): read_steam_name('game','manifest')
        with patch('steam_identity.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')):
            with self.assertRaises(SteamIdentityError): read_steam_name('game','manifest')


if __name__=='__main__': unittest.main()
