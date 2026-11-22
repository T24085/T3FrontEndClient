"""Linux entry: retain Steam's selected Proton/runtime command and replace only its game target.

Run --setup once and paste the printed option into TRIBES 3's Steam properties.
After that, Play in Steam opens the community lobby. No Steam configuration is
edited and Proton, Steam, Tailscale and the original game are not redistributed.
"""
import argparse
import ctypes as C
import errno
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import platform
import pty
import re
import selectors
import shlex
import shutil
import ssl
import subprocess
import sys
import time
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


def parse_windows_path(output):
    """Accept one unambiguous DOS path, even if Steam prints runtime notices."""
    matches = set()
    for line in output.decode('utf-8-sig', errors='replace').splitlines():
        line = line.removeprefix('\\\\?\\')
        if (re.fullmatch(r'[A-Za-z]:[\\/][^<>:"|?*\x00-\x1f\ufffd]*', line)
                and '..' not in PureWindowsPath(line).parts):
            matches.add(PureWindowsPath(line))
    return str(matches.pop()) if len(matches) == 1 else None


def proton_drives(compat_data):
    drives = []
    devices = Path(compat_data)/'pfx/dosdevices'
    try:
        for drive in devices.iterdir():
            if re.fullmatch('[a-zA-Z]:', drive.name) and drive.is_symlink():
                try:
                    target = drive.resolve(strict=True)
                except (OSError, RuntimeError):
                    continue
                if target.is_dir():
                    drives.append((target, PureWindowsPath(drive.name.upper() + '\\')))
    except OSError:
        pass
    return sorted(drives, key=lambda item: (-len(item[0].parts), str(item[1])))


def mapped_path(path, drives):
    for directory, drive in drives:
        if path.is_relative_to(directory):
            return parse_windows_path(str(drive.joinpath(*path.relative_to(directory).parts)).encode())
    return None


def prepare_launch(root, command, env, *, run=subprocess.run, workspace=None, state_directory=None,
                   join_directory=None):
    root = Path(root).resolve(strict=True)
    index, source = steam_command(command, env)
    for relative in ('python/pythonw.exe', 'linux_bootstrap.pyw', 'package-manifest.json'):
        if not (root/relative).is_file():
            raise ValueError('Extract the complete Linux client archive before opening it.')
    data_home = Path(env.get('XDG_DATA_HOME') or Path.home()/'.local/share').expanduser()
    if not data_home.is_absolute():
        raise ValueError('XDG_DATA_HOME must be an absolute directory.')
    state = Path(state_directory) if state_directory is not None else data_home/'Tribes3CommunityStarter'
    session = state/'linux-launches'/uuid.uuid4().hex
    session.mkdir(parents=True, mode=0o700)
    workspace = (Path(workspace) if workspace is not None else state/'sessions').resolve()
    if workspace == source or source in workspace.parents:
        raise ValueError('Community staging must be outside the original game.')
    workspace.mkdir(parents=True, exist_ok=True)
    # Import the Linux trust bundle into this launch, without disabling TLS or
    # installing anything into the Wine/Windows certificate store.
    ca_candidates = (ssl.get_default_verify_paths().cafile,
                     '/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt',
                     '/etc/ssl/cert.pem')
    cafile = next((Path(name) for name in ca_candidates if name and Path(name).is_file()
                   and 0 < Path(name).stat().st_size <= 4*1024*1024), None)
    if cafile is None:
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
    # Initialize this prefix with a real path. Snap may not export the Linux
    # root, and different paths can live on separate Wine drives.
    lookup = (join_directory if join_directory is not None else session)/'proton-preflight.log'
    print(f'Proton path-translation log: {lookup}', flush=True)
    deadline = time.monotonic() + 120
    with lookup.open('wb') as log:
        def probe(path, label):
            log.write(f'Translating {label}\n'.encode())
            log.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('Proton path translation timed out.')
            try:
                result = run(command[:index+1] + ['getcompatpath', str(path)], env=child_env,
                             stdout=subprocess.PIPE, stderr=log, timeout=min(90, remaining), check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError('Proton path translation timed out.') from exc
            log.write(f'Proton path translation exited with code {result.returncode}\n'.encode())
            log.write(result.stdout[:4096] + b'\n')
            if result.returncode or len(result.stdout) > 4096:
                raise ValueError(f'Proton could not translate the {label} path.')
            return parse_windows_path(result.stdout)

        launch_dir = probe(session, 'launch diagnostics')
        drives = proton_drives(child_env['STEAM_COMPAT_DATA_PATH'])

        def win(path, label, translated=None):
            mapped = mapped_path(path.resolve(), drives) or translated
            if not mapped and path != session:
                mapped = probe(path, label)
            if not mapped:
                raise ValueError(f'Proton did not return a usable Windows path for {label}.')
            return mapped

        package = PureWindowsPath(win(root, 'Clan Wars installation'))
        argv = command[:index+2] + [str(package/'python/pythonw.exe'), '-B', str(package/'linux_bootstrap.pyw'),
                                  '--game-dir', win(source, 'Steam game'), '--workspace', win(workspace, 'workspace'),
                                  '--launch-dir', win(session, 'launch diagnostics', launch_dir), '--ca-sha256', ca_sha]
        if join_directory is not None:
            argv += ['--ubuntu-join', win(join_directory, 'join request')]
    record = {'platform': platform.platform(), 'architecture': platform.machine(),
              'game_source': str(source), 'package': str(root), 'workspace': str(workspace),
              'proton': command[index], 'compat_data': child_env['STEAM_COMPAT_DATA_PATH'],
              'tls': 'Linux system CA snapshot; hostname and certificate verification required',
              'scope': 'Proton compatibility candidate; game readiness requires runtime evidence'}
    (session/'launch.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    return argv, child_env, session


def armor_viewport(tk, base):
    """Render the shared armor model in an EGL buffer and display it in Tk."""
    class LinuxArmorViewport(base):
        width, height = 420, 300

        def __init__(self, frame):
            self.frame = frame
            self.model = self.texture_owner = self.drag_start = self.pending = None
            self.context = self.surface = self.display = None
            self.texture_id = C.c_uint()
            self.label = tk.Label(frame, bg='#13202e', borderwidth=0)
            self.label.pack(fill='both', expand=True)
            self.reset_camera()
            for widget in (frame, self.label):
                widget.bind('<Map>', self.redraw)
                widget.bind('<ButtonPress-1>', self.start_drag)
                widget.bind('<B1-Motion>', self.drag)
                widget.bind('<ButtonRelease-1>', self.end_drag)
                widget.bind('<Button-4>', lambda _event: self.zoom(0.88))
                widget.bind('<Button-5>', lambda _event: self.zoom(1.14))
                widget.bind('<MouseWheel>', self.wheel)
            for event, action in (
                ('<Left>', lambda: self.orbit(-12, 0)), ('<Right>', lambda: self.orbit(12, 0)),
                ('<Up>', lambda: self.orbit(0, -10)), ('<Down>', lambda: self.orbit(0, 10)),
                ('<plus>', lambda: self.zoom(0.88)), ('<minus>', lambda: self.zoom(1.14)),
                ('<Home>', self.reset_camera),
            ):
                frame.bind(event, lambda _event, callback=action: callback())
            frame.bind('<Destroy>', self.close)

        def initialize(self):
            ptr, number, enum = C.c_void_p, C.c_int, C.c_uint
            integers, single, double = C.POINTER(number), C.c_float, C.c_double
            egl = self.egl = C.CDLL('libEGL.so.1')
            self.gl = C.CDLL('libGL.so.1')
            functions = (
                (egl, {
                    'eglGetPlatformDisplay': (ptr, enum, ptr, ptr),
                    'eglInitialize': (enum, ptr, ptr, ptr),
                    'eglBindAPI': (enum, enum),
                    'eglChooseConfig': (enum, ptr, integers, C.POINTER(ptr), number, integers),
                    'eglCreatePbufferSurface': (ptr, ptr, ptr, integers),
                    'eglCreateContext': (ptr, ptr, ptr, ptr, integers),
                    'eglMakeCurrent': (enum, ptr, ptr, ptr, ptr),
                    'eglDestroySurface': (enum, ptr, ptr), 'eglDestroyContext': (enum, ptr, ptr),
                    'eglTerminate': (enum, ptr),
                }),
                (self.gl, {
                    'glViewport': (None, number, number, number, number),
                    'glClearColor': (None, single, single, single, single), 'glClear': (None, enum),
                    'glMatrixMode': (None, enum), 'glLoadIdentity': (None,),
                    'glFrustum': (None, double, double, double, double, double, double),
                    'glTranslatef': (None, single, single, single),
                    'glRotatef': (None, single, single, single, single),
                    'glEnable': (None, enum), 'glDisable': (None, enum),
                    'glColorMaterial': (None, enum, enum),
                    'glLightfv': (None, enum, enum, C.POINTER(single)),
                    'glInterleavedArrays': (None, enum, number, ptr),
                    'glDrawArrays': (None, enum, number, number),
                    'glGenTextures': (None, number, C.POINTER(enum)),
                    'glDeleteTextures': (None, number, C.POINTER(enum)),
                    'glBindTexture': (None, enum, enum), 'glTexParameteri': (None, enum, enum, number),
                    'glPixelStorei': (None, enum, number),
                    'glTexImage2D': (None, enum, number, number, number, number, number, enum, enum, ptr),
                    'glReadPixels': (None, number, number, number, number, enum, enum, ptr),
                }),
            )
            for library, signatures in functions:
                for name, (result, *arguments) in signatures.items():
                    function = getattr(library, name)
                    function.restype, function.argtypes = result, arguments
            self.display = egl.eglGetPlatformDisplay(0x31DD, None, None)
            config, count = ptr(), number()
            # Pbuffer surface, full RGB and depth, desktop OpenGL.
            attributes = (number * 13)(0x3033, 1, 0x3024, 8, 0x3023, 8, 0x3022, 8,
                                       0x3025, 24, 0x3040, 8, 0x3038)
            if not (self.display and egl.eglInitialize(self.display, None, None) and egl.eglBindAPI(0x30A2)
                    and egl.eglChooseConfig(self.display, attributes, C.byref(config), 1, C.byref(count))
                    and count.value):
                self.close()
                raise OSError('The armor viewport could not open Linux OpenGL.')
            size = (number * 5)(0x3057, self.width, 0x3056, self.height, 0x3038)
            self.surface = egl.eglCreatePbufferSurface(self.display, config, size)
            self.context = egl.eglCreateContext(self.display, config, None, (number * 1)(0x3038))
            if not self.surface or not self.context:
                self.close()
                raise OSError('The armor viewport could not create a Linux OpenGL buffer.')

        def draw(self):
            self.pending = None
            if self.model is None or not self.frame.winfo_ismapped():
                return
            if not self.egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context):
                return
            try:
                gl = self.gl
                near = 0.2
                half_height = near * math.tan(math.radians(21))
                half_width = half_height * self.width / self.height
                gl.glViewport(0, 0, self.width, self.height)
                gl.glClearColor(0.075, 0.125, 0.18, 1)
                gl.glClear(0x4100)
                gl.glMatrixMode(0x1701)
                gl.glLoadIdentity()
                gl.glFrustum(-half_width, half_width, -half_height, half_height, near, 24)
                gl.glMatrixMode(0x1700)
                gl.glLoadIdentity()
                gl.glEnable(0x0B71)
                gl.glEnable(0x0B50)
                gl.glEnable(0x4000)
                gl.glEnable(0x0B57)
                gl.glColorMaterial(0x0408, 0x1602)
                gl.glLightfv(0x4000, 0x1203, (C.c_float * 4)(0.5, 0.8, 1, 0))
                gl.glLightfv(0x4000, 0x1200, (C.c_float * 4)(0.36, 0.36, 0.4, 1))
                gl.glTranslatef(0, 0, -self.distance)
                gl.glRotatef(self.pitch, 1, 0, 0)
                gl.glRotatef(self.yaw, 0, 1, 0)
                layout = self.bind_material(self.model)
                gl.glInterleavedArrays(layout, 0, C.cast(self.model.vertices, C.c_void_p))
                gl.glDrawArrays(4, 0, self.model.count)
                stride = self.width * 3
                pixels = C.create_string_buffer(stride * self.height)
                gl.glPixelStorei(0x0D05, 1)
                gl.glReadPixels(0, 0, self.width, self.height, 0x1907, 0x1401, pixels)
                raw = pixels.raw
                ppm = f'P6\n{self.width} {self.height}\n255\n'.encode()
                self.image = tk.PhotoImage(master=self.frame, format='PPM',
                                           data=ppm + b''.join(raw[i:i+stride] for i in range(len(raw)-stride, -1, -stride)))
                self.label.configure(image=self.image)
            finally:
                self.egl.eglMakeCurrent(self.display, None, None, None)

        def close(self, _event=None):
            if self.pending is not None:
                self.frame.after_cancel(self.pending)
                self.pending = None
            if self.context:
                self.egl.eglDestroyContext(self.display, self.context)
            if self.surface:
                self.egl.eglDestroySurface(self.display, self.surface)
            if self.display:
                self.egl.eglTerminate(self.display)
            self.context = self.surface = self.display = None

    return LinuxArmorViewport


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
    steam = parser.add_mutually_exclusive_group()
    steam.add_argument('--steam-launch', nargs=argparse.REMAINDER)
    steam.add_argument('--steam-probe', nargs=argparse.REMAINDER,
                       help='Check how Steam invokes the wrapper without starting Proton')
    argv = sys.argv[1:]
    # Parse only the wrapper arguments. Keep Steam's separators and options
    # opaque to argparse.
    boundary = next((i for i, value in enumerate(argv)
                     if value in ('--steam-launch', '--steam-probe')), None)
    args = parser.parse_args(argv if boundary is None else argv[:boundary + 1])
    command = [] if boundary is None else argv[boundary+1:]
    if command[:1] == ['--']:
        command = command[1:]
    if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        parser.error('This client requires 64-bit x86 Linux. ARM/Jetson is not supported.')
    if args.steam_probe is not None:
        try:
            steam_command(command, os.environ)
        except ValueError as exc:
            print(f'Steam handoff check failed: {exc}', file=sys.stderr)
            return 1
        print('Steam handed off the installed game and selected Proton. No game or Proton process was started.')
        return 0
    if args.steam_launch is None:
        option = setup_option(ROOT)
        message = ('In Steam: TRIBES 3 > Properties > Compatibility: enable Proton.\n'
                   'In General > Launch Options, paste this entire line:\n\n'+option+
                   '\n\nThen click Play in Steam to open Community Starter.\n'
                   'Keep Steam signed in while playing. No server files are included.')
        print(message)
        # Optional desktop clipboard helper. Setup remains usable without it.
        if shutil.which('zenity'):
            subprocess.run(['zenity', '--entry', '--title=TRIBES 3 Linux setup',
                            '--text=Paste this line into the game Steam Launch Options, then enable Proton and click Play.',
                            '--entry-text='+option], check=False)
        return 0
    try:
        argv, env, session = prepare_launch(ROOT, command, os.environ)
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
