"""Read the signed-in Steam user's persona name through their installed SDK.

The bounded helper initializes Steam in its own process, reads GetPersonaName,
and shuts down. It does not edit Steam, request credentials or authenticate the
player to our lobby; Tailscale admission remains a separate concern.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from player_names import display_name

PREFIX='STEAM_PERSONA_JSON|'
DLL_REL='Engine/Binaries/ThirdParty/Steamworks/Steamv153/Win64/steam_api64.dll'


class SteamIdentityError(RuntimeError): pass


def _read_native(game_source, manifest_path):
    if sys.platform!='win32': raise SteamIdentityError('Steam name lookup currently requires Windows.')
    source=Path(game_source).resolve(strict=True)
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    items=[item for item in manifest['files'] if item['path']==DLL_REL]
    if len(items)!=1: raise SteamIdentityError('The supported Steam API is absent from the game inventory.')
    item=items[0];dll=source/DLL_REL
    with dll.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if dll.stat().st_size!=item['bytes'] or actual!=item['sha256']:
        raise SteamIdentityError('The installed Steam API differs from the supported game version.')
    api=ctypes.CDLL(str(dll),winmode=0x1100)
    signatures={
        'SteamAPI_Init':([],ctypes.c_bool),
        'SteamAPI_Shutdown':([],None),
        'SteamAPI_SteamFriends_v017':([],ctypes.c_void_p),
        'SteamAPI_SteamUser_v021':([],ctypes.c_void_p),
        'SteamAPI_ISteamUser_GetSteamID':([ctypes.c_void_p],ctypes.c_uint64),
        'SteamAPI_ISteamFriends_GetPersonaName':([ctypes.c_void_p],ctypes.c_char_p),
    }
    for name,(args,result) in signatures.items():
        function=getattr(api,name);function.argtypes=args;function.restype=result
    if not api.SteamAPI_Init():
        raise SteamIdentityError('Start Steam and sign in to read your Steam player name.')
    try:
        user,friends=api.SteamAPI_SteamUser_v021(),api.SteamAPI_SteamFriends_v017()
        # BLoggedOn reports connection to Steam's servers, not whether the
        # local client has a current account. Display names need no live
        # Steam connection; Tailscale independently owns lobby admission.
        if not user or not friends or not api.SteamAPI_ISteamUser_GetSteamID(user):
            raise SteamIdentityError('Steam has no signed-in player.')
        raw=api.SteamAPI_ISteamFriends_GetPersonaName(friends)
        if not raw or len(raw)>128: raise SteamIdentityError('Steam returned no supported player name.')
        return display_name(raw.decode('utf-8'))
    finally:
        api.SteamAPI_Shutdown()


def read_steam_name(game_source, manifest_path, *, timeout=12):
    env=dict(os.environ,SteamAppId='2687970',SteamGameId='2687970')
    try:
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--probe',
                               '--game-dir',str(game_source),'--manifest',str(manifest_path)],
                              env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',
                              timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise SteamIdentityError('Steam name lookup timed out. Please check Steam and try again.') from exc
    if len(result.stdout)>32768 or len(result.stderr)>32768:
        raise SteamIdentityError('Steam name lookup returned excessive output.')
    messages=[line[len(PREFIX):] for line in result.stdout.splitlines() if line.startswith(PREFIX)]
    if len(messages)!=1: raise SteamIdentityError('Steam name lookup did not return a name.')
    value=json.loads(messages[0])
    if result.returncode or not isinstance(value,dict) or not isinstance(value.get('name'),str):
        raise SteamIdentityError(value.get('error','Steam name lookup failed.') if isinstance(value,dict) else 'Steam name lookup failed.')
    try: return display_name(value['name'])
    except ValueError as exc: raise SteamIdentityError(str(exc)) from exc


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe',action='store_true',required=True)
    parser.add_argument('--game-dir',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args()
    try: value={'name':_read_native(args.game_dir,args.manifest)};code=0
    except (OSError,ValueError,KeyError,AttributeError,SteamIdentityError) as exc:
        value={'error':str(exc)};code=1
    print(PREFIX+json.dumps(value,ensure_ascii=True),flush=True)
    return code


if __name__=='__main__': raise SystemExit(main())
