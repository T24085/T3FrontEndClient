"""Build a separate unreleased desktop client using matching verified Tk files."""
import hashlib
import json
import argparse
import runpy
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile
from community_maps import declared_maps, options
from build_dynamic_client import require_spectator_runtime

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'dynamic-client-development'
OUTPUT = ROOT / 'desktop-client-development'
PYTHON = ROOT / 'runtime-sources/Python-3.13.14'
PYTHON_ARCHIVE = ROOT / 'runtime-sources/python-3.13.14-amd64.zip'
PYTHON_ARCHIVE_SHA256 = 'f73b6535281b58eee6bcfb3403af2bcfac711ea1463d8340c47c3047248eddf7'
NOTICE_FILES = {
    'Python-3.13.14-LICENSE.txt': '78b12c3a81360b357002334f0e70ea0e92eebf7a9b358805c03c48484945f3bb',
    'zlib-1.3.1-LICENSE.txt': '845efc77857d485d91fb3e0b884aaa929368c717ae8186b66fe1ed2495753243',
}
ZLIB_DLL_SHA256 = 'bfb680c8f3eca7c150661be65c7e3bd16965aa5056be0b4f22992a1388c73504'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def connection_payloads(settings, policy):
    """Use the connection updater's endpoint contract for packaged defaults."""
    validate = runpy.run_path(str(ROOT/'update_lobby_connection.pyw'))['endpoint']
    settings = dict(validate(settings))
    policy = dict(policy)
    policy['server_address'] = settings['server_address']
    from dynamic_destination import destination
    for port in (18000, 18001):
        destination(settings['server_address']+':'+str(port), policy)
    return {name: (json.dumps(value, indent=2)+'\n').encode('utf-8') for name,value in (
        ('client-settings.json', settings), ('connection-policy.json', policy))}


def verify_runtime_sources():
    """Ensure every runtime file copied by this build matches the pinned archive."""
    prefixes = ('Lib/tkinter/', 'tcl/tcl8.6/', 'tcl/tk8.6/')
    names = {'pythonw.exe','python313.dll','LICENSE.txt','DLLs/_tkinter.pyd','DLLs/tcl86t.dll',
             'DLLs/tk86t.dll','DLLs/zlib1.dll'}
    def selected(name):
        parts=PurePosixPath(name).parts
        return (name in names or name.startswith(prefixes)) and not any(
            p in ('test','demos','__pycache__') or p.endswith('.pyc') for p in parts)
    with zipfile.ZipFile(PYTHON_ARCHIVE) as archive:
        entries={item.filename:item for item in archive.infolist() if not item.is_dir() and selected(item.filename)}
        actual=set(names)
        for prefix in prefixes:
            directory=PYTHON/Path(prefix)
            actual.update(p.relative_to(PYTHON).as_posix() for p in directory.rglob('*') if p.is_file() and selected(p.relative_to(PYTHON).as_posix()))
        if set(entries) != actual:
            raise ValueError('Extracted runtime inventory differs from the pinned archive.')
        for name, item in entries.items():
            with archive.open(item) as stream: expected=hashlib.file_digest(stream,'sha256').hexdigest()
            if sha(PYTHON/Path(name)) != expected:
                raise ValueError('Extracted runtime file differs from the pinned archive: '+name)


def launcher_artifacts(playtest):
    name = 'Start Community Starter' if playtest else 'Start Community Development'
    script = """Option Explicit

Dim fs, folder, exe, entry, shell, command

Set fs = CreateObject("Scripting.FileSystemObject")

folder = fs.GetParentFolderName(WScript.ScriptFullName)

exe = fs.BuildPath(folder, "python\\pythonw.exe")

entry = fs.BuildPath(folder, "community_starter.pyw")

If Not fs.FileExists(exe) Or Not fs.FileExists(entry) Then

  MsgBox "Extract the entire client ZIP before opening Community Starter.", 16, "TRIBES 3"

  WScript.Quit 1

End If

command = Chr(34) & exe & Chr(34) & " -B " & Chr(34) & entry & Chr(34)

Set shell = CreateObject("WScript.Shell")

shell.Run command, 1, False

"""
    batch = '@echo off\r\nstart "" "%SystemRoot%\\System32\\wscript.exe" "%~dp0' + name + '.vbs"\r\nexit /b\r\n'
    return {name+'.vbs':script, name+'.bat':batch}


def main():
    global SOURCE, OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE, help='Verified dynamic client candidate.')
    parser.add_argument('--output', type=Path, default=OUTPUT, help='New output directory; existing directories are never overwritten.')
    parser.add_argument('--playtest',action='store_true',help='Package the explicitly requested live lobby playtest launcher.')
    parser.add_argument('--connection-settings',type=Path,required=True,
                        help='Explicit target laptop lobby JSON; no host-PC default is inferred.')
    args = parser.parse_args()
    SOURCE, OUTPUT = args.source.resolve(strict=True), args.output.resolve()
    if SOURCE in OUTPUT.parents:
        raise ValueError('Candidate output must be outside the verified source package.')
    connections = connection_payloads(json.loads(args.connection_settings.read_bytes()),
                                      json.loads((SOURCE/'connection-policy.json').read_bytes()))
    if OUTPUT.exists():
        raise ValueError('Output already exists; choose a new candidate directory.')
    if not PYTHON_ARCHIVE.is_file() or sha(PYTHON_ARCHIVE) != PYTHON_ARCHIVE_SHA256:
        raise ValueError('Official runtime source archive is missing or its digest changed.')
    verify_runtime_sources()
    manifest = json.loads((SOURCE/'package-manifest.json').read_text(encoding='utf-8'))
    items = {}
    seen = set()
    for item in manifest['files']:
        rel = PurePosixPath(item['path'])
        if rel.is_absolute() or '..' in rel.parts or ':' in str(rel) or '\\' in item['path'] or not rel.parts:
            raise ValueError('Unsafe source path')
        if rel.as_posix().casefold() in seen:
            raise ValueError('Duplicate source path')
        seen.add(rel.as_posix().casefold())
        p = SOURCE.joinpath(*rel.parts).resolve(strict=True)
        if SOURCE not in p.parents:
            raise ValueError('Source inventory escapes package')
        if not p.is_file() or p.stat().st_size != item['bytes'] or sha(p) != item['sha256']:
            raise ValueError('Dynamic client failed verification: '+item['path'])
        items[item['path']] = p
    if manifest.get('startup_contract') != 'prepared-client-v1':
        raise ValueError('A modern prepared-client-v1 source package is required.')
    require_spectator_runtime(manifest, items)
    embedded_version = subprocess.check_output([str(SOURCE/'python/python.exe'),'-c','import sys;print(".".join(map(str,sys.version_info[:3])))'],text=True).strip()
    tkinter_version = subprocess.check_output([str(PYTHON/'python.exe'),'-c','import sys;print(".".join(map(str,sys.version_info[:3])))'],text=True).strip()
    if embedded_version != tkinter_version or sha(SOURCE/'python/python313.dll') != sha(PYTHON/'python313.dll'):
        raise ValueError('Tk files do not match the embedded Python runtime.')
    if embedded_version != '3.13.14' or sha(PYTHON/'DLLs/zlib1.dll') != ZLIB_DLL_SHA256:
        raise ValueError('Runtime changed; verify versions and matching third-party notices before building.')
    for name, expected in NOTICE_FILES.items():
        if sha(ROOT/'third-party-notices'/name) != expected:
            raise ValueError('Third-party notice changed: '+name)
    OUTPUT.mkdir(exist_ok=False)
    for name, source in items.items():
        if name == 'Join Server.bat':
            continue  # The desktop lobby selects the endpoint; this legacy shortcut requires a manual argument.
        dest = OUTPUT.joinpath(*PurePosixPath(name).parts)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
    for name in ('desktop_launcher.py','community_transport.py','community_game.py','map_catalog.py','compare_map_packages.py','community_maps.py','steam_identity.py','player_names.py','runtime_health.py','startup_progress.py','community_starter.pyw','verified_file_cache.py','startup_timing.py','startup_paths.py','bulk_asset_cache.py','client_preparation.py','client_bootstrap.py','bulk_verification_receipts.py'):
        shutil.copyfile(ROOT/name,OUTPUT/name)
    # The entry has one canonical producer; desktop wrapping must not revive a
    # stale generated CLI from its otherwise verified content source.
    shutil.copyfile(ROOT/'client_entry.py', OUTPUT/'client.py')
    shutil.copyfile(ROOT/'player_profile.py', OUTPUT/'player_profile.py')
    shutil.copyfile(PYTHON/'pythonw.exe',OUTPUT/'python/pythonw.exe')
    shutil.copytree(PYTHON/'Lib/tkinter',OUTPUT/'python/tkinter',ignore=shutil.ignore_patterns('__pycache__','*.pyc','test'))
    for name in ('_tkinter.pyd','tcl86t.dll','tk86t.dll','zlib1.dll'):
        shutil.copyfile(PYTHON/'DLLs'/name,OUTPUT/'python'/name)
    for name in ('tcl8.6','tk8.6'):
        shutil.copytree(PYTHON/'tcl'/name,OUTPUT/'python/tcl'/name,ignore=shutil.ignore_patterns('demos','__pycache__','*.pyc'))
    shutil.copyfile(PYTHON/'LICENSE.txt',OUTPUT/'licenses/Python-installed-Tk-source-LICENSE.txt')
    shutil.copyfile(PYTHON/'tcl/tk8.6/license.terms',OUTPUT/'licenses/Tcl-Tk-license.terms')
    for name in NOTICE_FILES:
        shutil.copyfile(ROOT/'third-party-notices'/name,OUTPUT/'licenses'/name)
    for name,data in connections.items():
        (OUTPUT/name).write_bytes(data)
    for name, text in launcher_artifacts(args.playtest).items():
        (OUTPUT/name).write_text(text,encoding='utf-8',newline='')
    readme='Development only. The lobby service has not been launched. Remote identity, admission, game joining and packaging remain unqualified. Do not distribute this build.\n'
    if args.playtest:
        readme='''TRIBES 3 - COMMUNITY LOBBY PLAYTEST

1. Start Steam with your own matching TRIBES 3 installation and connect Tailscale.
2. Extract this entire ZIP into a fresh folder. Run Start Community Starter.vbs (the .bat shortcut also works).
3. Your current Steam name is filled in automatically.
4. Create a lobby, or join using the code from your lobby leader.
5. Choose your team. The leader chooses the map and can move players between teams.
6. The leader clicks Start match. Wait for the host to be ready, then click Join game.

A solo player can start a practice match after choosing a team. Multiplayer
matches need a player on each team. The first file check and game launch can
take several minutes. Leave the launcher open while playing; close normally.
The leader can stop a match and reset the lobby to select the next map.

Maps: '''+', '.join(item['label'] for item in options(declared_maps(manifest)))+'''.

Your PC runs the game client. Match instances run on the community host PC.
No server launcher, server objective logic, TLS keys, owner configuration,
original game executable or original game Paks are included in this ZIP.
The launcher uses an isolated game copy and profile; the original installation
is a read-only input. Python and UE4SS are included with their license notices.

This is a private experimental playtest. Bots and functional base systems remain
under development. The clear and weather Snowblind variants are separate map
options. Remote players and multiple populated matches still need testing.
'''
    if args.playtest and manifest.get('spectator_contract')=='native-spectator-v1':
        readme+='''
SPECTATING

Open Live matches, select a match, then click Spectate.
F5/F6 switch players. F7 selects first person; F8 selects third person.
Stop watching closes only your viewer. Keep Starter open while watching.
The leader can disable spectators during lobby setup. Spectators have separate
seats and do not join either team or count toward the player load-in countdown.
Both the community server and the watching client need this update.
'''
    (OUTPUT/'README-FIRST.txt').write_text(readme,encoding='utf-8')
    provenance={'embedded_python':embedded_version,'tk_source_python':tkinter_version,
                'connection_settings_sha256':sha(args.connection_settings),
                'source_manifest_sha256':sha(SOURCE/'package-manifest.json'),
                'tk_source_archive_sha256':PYTHON_ARCHIVE_SHA256,
                'tkinter_pyd_sha256':sha(OUTPUT/'python/_tkinter.pyd'),
                'tk_dll_sha256':sha(OUTPUT/'python/tk86t.dll'),'tcl_dll_sha256':sha(OUTPUT/'python/tcl86t.dll'),
                'zlib_dll_sha256':sha(OUTPUT/'python/zlib1.dll'),
                'status':'private lobby playtest; full remote, capacity and gameplay qualification incomplete' if args.playtest else 'development only; full license and portability review required before distribution'}
    (OUTPUT/'desktop-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    out = []
    for p in sorted(OUTPUT.rglob('*')):
        if p.is_file():
            out.append({'path':p.relative_to(OUTPUT).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
    result_manifest = dict(manifest)
    result_manifest.update(build_id='desktop-client-development', files=out)
    (OUTPUT/'package-manifest.json').write_text(json.dumps(result_manifest,indent=2)+'\n')
    print('Unreleased desktop client prepared:',OUTPUT,flush=True)


if __name__ == '__main__': main()
