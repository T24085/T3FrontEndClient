"""Linux entry: retain Steam's selected Proton/runtime command and replace only its game target.

Run --setup once and paste the printed option into TRIBES 3's Steam properties.
After that, Play in Steam opens the community lobby. No Steam configuration is
edited and Proton, Steam, Tailscale and the original game are not redistributed.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import pty
import selectors
import shlex
import shutil
import ssl
import subprocess
import sys
import uuid

APP_ID = '2687970'
GAME_BINARY = Path('Topaz/Binaries/Win64/TribesRivals.exe')
ROOT = Path(__file__).resolve().parent


def setup_option(root):
    return shlex.quote(str(Path(root).resolve() / 'Start Community Starter.sh')) + ' --steam-launch %command%'


def merge_dll_overrides(current):
    """Keep unrelated overrides, including grouped names; set the UE4SS proxy explicitly."""
    kept = []
    for clause in current.split(';'):
        if not clause.strip():
            continue
        names, separator, mode = clause.partition('=')
        if not separator:
            raise ValueError('An existing WINEDLLOVERRIDES clause is malformed.')
        remaining = [name.strip() for name in names.split(',')
                     if name.strip().lower().removesuffix('.dll') != 'dwmapi']
        if remaining:
            kept.append(','.join(remaining) + '=' + mode)
    return ';'.join(kept + ['dwmapi=n,b'])


def steam_command(command, env):
    """Find the original game installation and the exact Steam-selected Proton invocation."""
    if env.get('SteamAppId') != APP_ID or env.get('SteamGameId') not in (None, APP_ID):
        raise ValueError('Use Play on TRIBES 3 in Steam, with the launch option from --setup.')
    compat = env.get('STEAM_COMPAT_DATA_PATH')
    if not compat or not Path(compat).is_absolute():
        raise ValueError('Steam did not supply a Proton compatibility prefix. Enable Proton for TRIBES 3.')
    proton = [i for i, value in enumerate(command) if Path(value).name == 'proton']
    if len(proton) != 1 or not Path(command[proton[0]]).is_file():
        raise ValueError('No unique Steam Proton command was supplied. Force a Proton version in game properties.')
    index = proton[0]
    if index + 2 >= len(command) or command[index+1] not in ('run', 'waitforexitandrun'):
        raise ValueError('Unsupported Steam Proton invocation; attach linux-launcher.log when reporting it.')
    # Proton's program is positional. Never select a different .exe from options.
    target = Path(command[index+2])
    if not target.is_absolute() or target.suffix.lower() != '.exe' or not target.is_file():
        raise ValueError('Steam did not supply an installed Windows game executable.')
    install = env.get('STEAM_COMPAT_INSTALL_PATH')
    candidates = [Path(install)] if install else list(target.parents)[:5]
    candidates = list(dict.fromkeys(p.resolve() for p in candidates if (p/GAME_BINARY).is_file()))
    if len(candidates) != 1:
        raise ValueError('Cannot identify the TRIBES 3 installation selected by Steam.')
    source = candidates[0]
    if source not in target.resolve().parents:
        raise ValueError('Steam game target does not belong to its selected installation.')
    return index, source


def windows_path(root, value):
    drive = PureWindowsPath(root.strip())
    if not drive.is_absolute() or drive.parts != (drive.anchor,) or drive.anchor.startswith('\\\\'):
        raise ValueError('Proton did not return an absolute DOS mapping for the Linux root.')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('A Linux launch path was not absolute.')
    return str(drive.joinpath(*path.parts[1:]))


def prepare_launch(root, command, env, *, run=subprocess.run):
    root = Path(root).resolve(strict=True)
    index, source = steam_command(command, env)
    for relative in ('python/pythonw.exe', 'linux_bootstrap.pyw', 'package-manifest.json'):
        if not (root/relative).is_file():
            raise ValueError('Extract the complete Linux client archive before opening it.')
    data_home = Path(env.get('XDG_DATA_HOME') or Path.home()/'.local/share').expanduser()
    if not data_home.is_absolute():
        raise ValueError('XDG_DATA_HOME must be an absolute directory.')
    state = data_home/'Tribes3CommunityStarter'
    session = state/'linux-launches'/uuid.uuid4().hex
    session.mkdir(parents=True, mode=0o700)
    workspace = state/'sessions'
    workspace.mkdir(parents=True, exist_ok=True)
    if workspace == source or source in workspace.parents:
        raise ValueError('Community staging must be outside the original game.')
    # Import the Linux trust bundle into this launch, without disabling TLS or
    # installing anything into the Wine/Windows certificate store.
    cafile = ssl.get_default_verify_paths().cafile
    if not cafile or not Path(cafile).is_file() or not 0 < Path(cafile).stat().st_size <= 4*1024*1024:
        raise ValueError('Linux system CA certificates are unavailable. Install your distribution CA certificates.')
    ca = session/'ca-bundle.pem'
    shutil.copyfile(cafile, ca)
    ca.chmod(0o600)
    ca_sha = hashlib.sha256(ca.read_bytes()).hexdigest()
    child_env = dict(env)
    child_env['WINEDLLOVERRIDES'] = merge_dll_overrides(env.get('WINEDLLOVERRIDES', ''))
    # Wine's inherited Unix redirections can lack Windows console handles.
    # Python's documented file-stream mode also applies to our owned children.
    child_env['PYTHONLEGACYWINDOWSSTDIO'] = '1'
    child_env['PYTHONIOENCODING'] = 'utf-8'
    # Use Proton's own path translator once. Do not assume a Z: mapping or a
    # default prefix; retain any Steam runtime/container command before Proton.
    result = run(command[:index+1] + ['getcompatpath', '/'], env=child_env,
                 capture_output=True, timeout=90, check=False)
    if result.returncode or len(result.stdout) > 4096:
        raise ValueError('Proton could not initialize or translate paths; check its installation in Steam.')
    dos_root = result.stdout.decode('utf-8-sig').strip()
    win = lambda p: windows_path(dos_root, p)
    argv = command[:index+2] + [win(root/'python/pythonw.exe'), '-B', win(root/'linux_bootstrap.pyw'),
                              '--game-dir', win(source), '--workspace', win(workspace),
                              '--launch-dir', win(session), '--ca-sha256', ca_sha]
    record = {'platform': platform.platform(), 'architecture': platform.machine(),
              'game_source': str(source), 'package': str(root), 'workspace': str(workspace),
              'proton': command[index], 'compat_data': child_env['STEAM_COMPAT_DATA_PATH'],
              'tls': 'Linux system CA snapshot; hostname and certificate verification required',
              'scope': 'Proton compatibility candidate; game readiness requires runtime evidence'}
    (session/'launch.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    return argv, child_env, session


def run_in_terminal(argv, env, cwd, log):
    """Give Wine valid terminal handles without opening a terminal window.

    Direct Unix file redirection can fail before Windows Python initializes its
    streams. Keep a private PTY and drain it to a bounded log until the original
    child object is terminal; never signal Steam or a shared wineserver by name.
    """
    master, slave = pty.openpty()
    selector = selectors.DefaultSelector()
    written, capped, log_error = 0, False, None
    try:
        process = subprocess.Popen(argv, env=env, cwd=cwd, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        slave = None
        selector.register(master, selectors.EVENT_READ)
        eof = False
        while True:
            events = [] if eof else selector.select(timeout=.2)
            for _, _ in events:
                try:
                    block = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    block = b''
                if not block:
                    eof = True
                    selector.unregister(master)
                    break
                try:
                    if log_error is None and written < 16*1024*1024:
                        keep = block[:16*1024*1024-written]
                        log.write(keep)
                        written += len(keep)
                    elif log_error is None and not capped:
                        log.write(b'\n[Launcher output limit reached; continuing without additional log output.]\n')
                        capped = True
                except OSError as exc:
                    # A full logging disk must not discard the live child owner.
                    log_error = exc
            if process.poll() is not None:
                if log_error is not None:
                    raise OSError('Launcher logging failed after the client finished: '+str(log_error))
                return process.wait()
            if eof:
                # Waiting through the original Popen handle avoids a busy loop
                # if the program closes stdio while keeping its GUI running.
                code = process.wait()
                if log_error is not None:
                    raise OSError('Launcher logging failed after the client finished: '+str(log_error))
                return code
    finally:
        selector.close()
        if slave is not None:
            os.close(slave)
        os.close(master)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--steam-launch', nargs=argparse.REMAINDER)
    argv = sys.argv[1:]
    if '--steam-launch' in argv:
        index = argv.index('--steam-launch')
        args = parser.parse_args(argv[:index + 1])
        command = argv[index + 1:]
        # Steam can put one separator before its command. Keep the separators
        # inside that command opaque to argparse for reaper and the runtime.
        args.steam_launch = command[1:] if command[:1] == ['--'] else command
    else:
        args = parser.parse_args(argv)
    if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        parser.error('This client requires 64-bit x86 Linux. ARM/Jetson is not supported.')
    if args.steam_launch is None:
        option = setup_option(ROOT)
        message = ('In Steam: TRIBES 3 > Properties > Compatibility: enable Proton.\n'
                   'In General > Launch Options, paste this entire line:\n\n'+option+
                   '\n\nThen click Play in Steam to open Community Starter.\n'
                   'Keep Steam and Tailscale connected. No server files are included.')
        print(message)
        # Optional desktop clipboard helper. Setup remains usable without it.
        if shutil.which('zenity'):
            subprocess.run(['zenity', '--entry', '--title=TRIBES 3 Linux setup',
                            '--text=Paste this line into the game Steam Launch Options, then enable Proton and click Play.',
                            '--entry-text='+option], check=False)
        return 0
    try:
        argv, env, session = prepare_launch(ROOT, args.steam_launch, os.environ)
        print('Community Starter launch log: '+str(session/'linux-launcher.log'), flush=True)
        # Retain the actual child object. Do not kill a shared wineserver, Steam
        # session, or any process looked up later by PID/name.
        with (session/'linux-launcher.log').open('wb') as log:
            return run_in_terminal(argv, env, ROOT, log)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print('Community Starter: '+str(exc), file=sys.stderr)
        if shutil.which('zenity'):
            subprocess.run(['zenity', '--error', '--title=TRIBES 3 Community Starter', '--text='+str(exc)], check=False)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
