"""Separate direct-host Starter entry with local per-device credentials."""
from collections import deque
from contextlib import closing, contextmanager
import ctypes as C
from ctypes import wintypes as W
import http.client
import json
import os
import pathlib
import queue
import re
import secrets
import socket
import threading
import time
from direct_network import (ENDPOINT_FIELDS, ENROLL_ROUTE, GROUP_FILE, MATCH_SLOT_LIMIT, MATCH_UDP_BASES,
                            MAX_DEVICES, TOKEN, UdpClient,
                            VoiceFrames, VOICE_AUDIO, VOICE_FRAME_BYTES, VOICE_KEEPALIVE, VOICE_PROTOCOL,
                            VOICE_RELEASE, VOICE_ROUTE, VOICE_SAMPLE_RATE,
                            locked_state, read_json, validate_endpoint, validate_group, write_json)
from community_transport import CommunityClient, CommunityError, PinnedHTTPSConnection
from dynamic_destination import DIRECT_BRIDGE_POLICY

ROOT=pathlib.Path(__file__).resolve().parent
DEFAULT_PTT_KEY = 0x78  # F9
PTT_KEY_NAMES = {
    **{key: chr(key) for key in (*range(0x30, 0x3a), *range(0x41, 0x5b))},
    **{0x70 + i: f'F{i + 1}' for i in range(24)},
    **{0x60 + i: f'Numpad {i}' for i in range(10)},
    0x08: 'Backspace', 0x09: 'Tab', 0x0d: 'Enter', 0x13: 'Pause',
    0x14: 'Caps Lock', 0x20: 'Space', 0x21: 'Page Up', 0x22: 'Page Down',
    0x23: 'End', 0x24: 'Home', 0x25: 'Left', 0x26: 'Up', 0x27: 'Right',
    0x28: 'Down', 0x2d: 'Insert', 0x2e: 'Delete', 0x5d: 'Menu',
    0x6a: 'Numpad *', 0x6b: 'Numpad +', 0x6d: 'Numpad −', 0x6e: 'Numpad .',
    0x6f: 'Numpad /', 0x90: 'Num Lock', 0x91: 'Scroll Lock',
    0xba: ';', 0xbb: '=', 0xbc: ',', 0xbd: '-', 0xbe: '.', 0xbf: '/',
    0xc0: '`', 0xdb: '[', 0xdc: '\\', 0xdd: ']', 0xde: "'", 0xe2: 'OEM 102',
}
WAVE_MAPPER = 0xffffffff
WAVE_DONE = 1
WAVE_IN_QUEUE = 0x10


def proximity_prompt(key):
    return f'Hold {PTT_KEY_NAMES[key]} to talk'


def read_proximity_key(path):
    if path is not None:
        try:
            settings = read_json(path, 1024)
            key = settings.get('key') if isinstance(settings, dict) else None
            if type(key) is int and key in PTT_KEY_NAMES:
                return key
        except (OSError, ValueError):
            pass
    return DEFAULT_PTT_KEY


def choose_proximity_key(parent, save):
    import tkinter as tk
    from tkinter import ttk

    dialog = tk.Toplevel(parent)
    dialog.title('Proximity voice key')
    dialog.transient(parent)
    dialog.resizable(False, False)
    prompt = tk.StringVar(dialog, 'Press a key to bind. Esc cancels.')
    ttk.Label(dialog, textvariable=prompt, wraplength=300, padding=16).pack()

    def capture(event):
        if event.keysym == 'Escape':
            dialog.destroy()
        elif event.keycode not in PTT_KEY_NAMES:
            prompt.set('Choose a keyboard key such as a letter, Space, or F9.')
        else:
            try:
                save(event.keycode)
            except OSError:
                prompt.set('Could not save the key. Press it again to retry.')
            else:
                dialog.destroy()
        return 'break'

    dialog.bind('<KeyPress>', capture)
    dialog.wait_visibility()
    dialog.grab_set()
    dialog.focus_set()


class WaveFormat(C.Structure):
    _fields_ = [('format', W.WORD), ('channels', W.WORD), ('rate', W.DWORD),
                ('bytes_per_second', W.DWORD), ('alignment', W.WORD),
                ('bits', W.WORD), ('extension_size', W.WORD)]


class WaveHeader(C.Structure):
    _fields_ = [('data', C.c_void_p), ('size', W.DWORD), ('recorded', W.DWORD),
                ('user', C.c_size_t), ('flags', W.DWORD), ('loops', W.DWORD),
                ('next', C.c_void_p), ('reserved', C.c_size_t)]


class WindowsVoiceDevice:
    """Small, bounded PCM buffers on the Windows default communications path."""
    def __init__(self, capture):
        self.capture = capture
        self.handle = W.HANDLE()
        self.buffers = deque()
        dll = C.WinDLL('winmm')
        self.api = {}
        for suffix, arguments in (
            ('Open', [C.POINTER(W.HANDLE), W.UINT, C.POINTER(WaveFormat),
                      C.c_size_t, C.c_size_t, W.DWORD]),
            ('PrepareHeader', [W.HANDLE, C.POINTER(WaveHeader), W.UINT]),
            ('UnprepareHeader', [W.HANDLE, C.POINTER(WaveHeader), W.UINT]),
            ('AddBuffer' if capture else 'Write', [W.HANDLE, C.POINTER(WaveHeader), W.UINT]),
            ('Reset', [W.HANDLE]), ('Close', [W.HANDLE]),
        ):
            call = getattr(dll, ('waveIn' if capture else 'waveOut') + suffix)
            call.argtypes, call.restype = arguments, W.UINT
            self.api[suffix] = call
        if capture:
            dll.waveInStart.argtypes, dll.waveInStart.restype = [W.HANDLE], W.UINT
            self.api['Start'] = dll.waveInStart
        fmt = WaveFormat(1, 1, VOICE_SAMPLE_RATE, VOICE_SAMPLE_RATE * 2, 2, 16, 0)
        self.call('Open', C.byref(self.handle), WAVE_MAPPER, C.byref(fmt), 0, 0, 0)
        try:
            for _ in range(4):
                data = C.create_string_buffer(VOICE_FRAME_BYTES)
                header = WaveHeader(C.addressof(data), VOICE_FRAME_BYTES)
                self.header_call('PrepareHeader', header)
                self.buffers.append((data, header))
                if capture:
                    self.header_call('AddBuffer', header)
            if capture:
                self.call('Start', self.handle)
        except OSError:
            self.close()
            raise

    def call(self, name, *args):
        result = self.api[name](*args)
        if result:
            raise OSError(f'Windows voice device error {result} ({name}).')

    def header_call(self, name, header):
        self.call(name, self.handle, C.byref(header), C.sizeof(header))

    def recorded(self):
        frames = []
        for _ in range(len(self.buffers)):
            data, header = self.buffers[0]
            if not header.flags & WAVE_DONE:
                break
            if header.recorded == VOICE_FRAME_BYTES:
                frames.append(data.raw)
            self.header_call('AddBuffer', header)
            self.buffers.rotate(-1)
        return frames

    def play(self, frame):
        data, header = self.buffers[0]
        if not header.flags & WAVE_IN_QUEUE:
            data.raw = frame
            self.header_call('Write', header)
            self.buffers.rotate(-1)

    def close(self):
        if self.handle:
            self.api['Reset'](self.handle)
            for _, header in self.buffers:
                self.api['UnprepareHeader'](self.handle, C.byref(header), C.sizeof(header))
            self.api['Close'](self.handle)
            self.handle = None


class OwnedGameFocus:
    """Match the foreground window against the exact staged game's process."""
    def __init__(self, run):
        record = json.loads((run / 'execution/execution.json').read_bytes())
        executable = run / 'game/Topaz/Binaries/Win64/TribesRivals.exe'
        self.pid = record.get('pid')
        if (record.get('status') != 'running' or record.get('assigned_suspended') is not True
                or type(self.pid) is not int or self.pid < 1
                or pathlib.Path(record['argv'][0]) != executable):
            raise ValueError('Voice requires the owned game session.')
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.user.GetForegroundWindow.argtypes = []
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.user.GetWindowThreadProcessId.restype = W.DWORD
        self.user.GetAsyncKeyState.argtypes = [C.c_int]
        self.user.GetAsyncKeyState.restype = C.c_short
        self.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = W.BOOL
        self.kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        self.kernel.WaitForSingleObject.restype = W.DWORD
        self.kernel.CloseHandle.argtypes = [W.HANDLE]
        self.kernel.CloseHandle.restype = W.BOOL
        self.handle = self.kernel.OpenProcess(0x101000, False, self.pid)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        buffer = C.create_unicode_buffer(32768)
        size = W.DWORD(len(buffer))
        if (not self.kernel.QueryFullProcessImageNameW(self.handle, 0, buffer, C.byref(size))
                or pathlib.Path(buffer.value) != executable):
            self.close()
            raise ValueError('Voice game process identity changed.')

    def alive(self):
        return self.kernel.WaitForSingleObject(self.handle, 0) == 258

    def focused(self):
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), C.byref(pid))
        return pid.value == self.pid and self.alive()

    def pressed(self, key):
        return bool(self.user.GetAsyncKeyState(key) & 0x8000)

    def close(self):
        self.kernel.CloseHandle(self.handle)


def proximity_connection(lobby, headers, grant):
    conn = PinnedHTTPSConnection(lobby.hostname, lobby.port, lobby.server_address,
                                 context=lobby.context, timeout=2)
    try:
        conn.request('GET', VOICE_ROUTE, headers={
            **headers, 'Origin': lobby.origin, 'Connection': 'Upgrade', 'Upgrade': VOICE_PROTOCOL,
            'X-Voice-Match': grant['matchId'], 'X-Voice-Grant': grant['id'],
        })
        with conn.getresponse() as response:
            if (response.status != 101 or response.getheader('Upgrade') != VOICE_PROTOCOL
                    or response.getheader('Connection', '').lower() != 'upgrade'):
                raise ValueError('The match did not accept proximity voice.')
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.sock.settimeout(0.012)
        return conn
    except BaseException:
        conn.close()
        raise


def run_proximity_voice(connection, focus, active, status, binding):
    frames = VoiceFrames()
    connection.sendall(VOICE_KEEPALIVE)
    next_heartbeat = time.monotonic() + 1
    last_receive = time.monotonic()
    key = binding()
    previous_press = focus.pressed(key)
    capture = playback = None
    playback_failed = False
    status(proximity_prompt(key))
    try:
        while active() and focus.alive() and time.monotonic() - last_receive < 5:
            selected_key = binding()
            changed = selected_key != key
            key = selected_key
            focused, pressed = focus.focused(), focus.pressed(key)
            if capture is not None and (changed or not (focused and pressed)):
                capture.close()
                capture = None
                connection.sendall(VOICE_RELEASE)
                status(proximity_prompt(key))
            if not focused and playback is not None:
                playback.close()
                playback = None
            if focused and pressed and not (changed or previous_press):
                try:
                    capture = WindowsVoiceDevice(capture=True)
                except OSError:
                    status('Microphone unavailable')
                else:
                    status('Proximity mic active')
            previous_press = pressed
            if capture is not None:
                for audio in capture.recorded():
                    if not active() or binding() != key or not focus.focused() or not focus.pressed(key):
                        break
                    connection.sendall(VOICE_AUDIO + audio)
            now = time.monotonic()
            if now >= next_heartbeat:
                connection.sendall(VOICE_KEEPALIVE)
                next_heartbeat = now + 1
            try:
                data = connection.recv(4096)
            except TimeoutError:
                continue
            if not data:
                return
            last_receive = time.monotonic()
            for kind, audio in frames.feed(data):
                if kind != VOICE_AUDIO or not active() or not focus.focused() or playback_failed:
                    continue
                try:
                    if playback is None:
                        playback = WindowsVoiceDevice(capture=False)
                    playback.play(audio)
                except OSError:
                    playback_failed = True
                    status('Voice playback unavailable')
    finally:
        if capture is not None:
            capture.close()
        if playback is not None:
            playback.close()

def validate_connection(d,*,local_test=False):
    if not isinstance(d,dict)or set(d)!=ENDPOINT_FIELDS|{'format','access_token'}or d['format']!=1:
        raise ValueError('Choose an invitation exported by the direct host.')
    validate_endpoint(d,local_test=local_test)
    if not isinstance(d['access_token'],str)or not TOKEN.fullmatch(d['access_token']):
        raise ValueError('Invalid invitation credential.')
    return dict(d)

class DirectClient(CommunityClient):
    address_error = 'A direct host must have a public IPv4 address.'
    reconnect_requires_new_game = True

    @staticmethod
    def accepts_server_address(address):
        return address.is_global and not address.is_multicast

    def __init__(self,connection,*,ssl_context=None,test_source=None,proximity_settings=None):
        d=validate_connection(connection,local_test=test_source is not None)
        super().__init__(d['hostname'],d['https_port'],d['public_address'],dict(DIRECT_BRIDGE_POLICY),
                         ssl_context=ssl_context,test_source=test_source)
        self.connection=d;self.access_token=d['access_token'];self.direct_session=secrets.token_hex(16);self.proxies={}
        self.proximity_supported = False
        self.proximity_enabled = threading.Event()
        self.proximity_enabled.set()
        self.proximity_settings = proximity_settings
        self.proximity_key = read_proximity_key(proximity_settings)
        self.proximity_status = proximity_prompt(self.proximity_key)
        self.public_supported = self.public_only = False
        self.armor_supported = False
        self.public_transport_state = None

    def capabilities(self):
        caps = super().capabilities()
        self.proximity_supported = os.name == 'nt' and caps.get('proximityVoice') == VOICE_PROTOCOL
        self.public_supported = caps.get('publicCTF') is True
        self.public_only = self.public_supported and caps.get('publicOnly') is True
        self.armor_supported = caps.get('armorSuits') == 1
        return caps

    def armor_suits(self, **data):
        return self._request('armor-suits', data, use_lobby_token=False)

    def _public(self, action, **data):
        response = self._request('public-' + action, data, use_lobby_token=False)
        if action == 'leave':
            return response
        state = response.get('public')
        if not isinstance(state, dict) or state.get('phase') not in ('loading', 'playing', 'voting', 'traveling'):
            raise CommunityError('The host returned invalid Public CTF status.')
        return state

    def public_join(self, name):
        return self._public('join', name=name)

    def public_map(self):
        deadline = time.monotonic() + 100
        while True:
            state = self.public_state()
            map_id, fingerprint = state.get('map'), state.get('contentHash')
            if (state['phase'] == 'playing' and isinstance(map_id, str)
                    and self.map_label(map_id) is not None and isinstance(fingerprint, str)
                    and re.fullmatch('[0-9a-f]{64}', fingerprint)):
                return {'map': map_id, 'contentHash': fingerprint}
            if time.monotonic() >= deadline:
                raise CommunityError(state.get('error') or 'Public CTF is preparing the next map. Try joining again.')
            time.sleep(2)

    def public_state(self, *, renew=False):
        state = self._public('state')
        if renew:
            current = state.get('round'), state['phase']
            with self.lock:
                previous = self.public_transport_state
                if previous is not None and (current[0] != previous[0] or
                        (previous[1] == 'playing' and current[1] != 'playing')):
                    for proxy in self.proxies.values():
                        proxy.allow_rebind()
                if self.proxies:
                    self.public_transport_state = current
                if state.get('target'):
                    self._validated_target(state['target'], state.get('map'), public=True, existing_only=True)
        return state

    def public_target(self):
        deadline = time.monotonic() + 45
        while True:
            state = self.public_state()
            if state.get('target'):
                with self.lock:
                    target = self._validated_target(state['target'], state.get('map'), public=True)
                    self.public_transport_state = (state.get('round'), state['phase'])
                    return target
            if not state.get('team') or time.monotonic() >= deadline:
                raise CommunityError(state.get('error') or 'Your public match seat was not ready. Try joining again.')
            time.sleep(1)

    def public_vote(self, round_id, map_id):
        return self._public('vote', round=round_id, map=map_id)

    def public_leave(self):
        self._public('leave')

    def set_proximity_voice(self, enabled):
        if enabled:
            self.proximity_enabled.set()
            self.proximity_status = proximity_prompt(self.proximity_key)
        else:
            self.proximity_enabled.clear()
            self.proximity_status = 'Proximity voice muted'

    def bind_proximity_key(self, key):
        if type(key) is not int or key not in PTT_KEY_NAMES:
            raise ValueError('Unsupported proximity voice key.')
        if self.proximity_settings is not None:
            write_json(self.proximity_settings, {'key': key})
        self.proximity_key = key
        if self.proximity_enabled.is_set():
            self.proximity_status = proximity_prompt(key)

    @contextmanager
    def proximity_game(self, ready_run):
        with self.lock:
            proxy = next(iter(self.proxies.values()), None)
            admission = dict(proxy.grant) if proxy is not None else None
            headers = self.request_headers()
        if not self.proximity_supported or admission is None or self.test_source:
            yield
            return

        stop = threading.Event()

        def status(text):
            if self.proximity_enabled.is_set() and not stop.is_set():
                self.proximity_status = text

        def worker():
            focus = None
            try:
                while not stop.wait(0.15) and focus is None:
                    run = ready_run()
                    if run is not None:
                        try:
                            focus = OwnedGameFocus(run)
                        except (OSError, ValueError, KeyError, IndexError, TypeError):
                            continue
                if focus is None:
                    return
                with closing(focus):
                    while not stop.is_set() and focus.alive():
                        if not self.proximity_enabled.is_set():
                            stop.wait(0.15)
                            continue
                        try:
                            with closing(proximity_connection(self, headers, admission)) as conn:
                                run_proximity_voice(conn.sock, focus,
                                    lambda: not stop.is_set() and self.proximity_enabled.is_set() and ready_run() is not None,
                                    status, lambda: self.proximity_key)
                        except (OSError, ValueError, http.client.HTTPException):
                            status('Proximity voice reconnecting…')
                        if stop.wait(2):
                            return
            finally:
                status(proximity_prompt(self.proximity_key))

        thread = threading.Thread(target=worker, name='proximity-voice-client', daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(2.5)
            self.proximity_status = (proximity_prompt(self.proximity_key) if self.proximity_enabled.is_set()
                                     else 'Proximity voice muted')

    def request_headers(self):
        return dict(super().request_headers(), **{
            'Authorization': 'Bearer ' + self.access_token,
            'X-Direct-Session': self.direct_session,
        })

    def begin_game_attempt(self):
        """Use a new admission and native socket for each owned game process."""
        with self.lock:
            self.close()
            self.direct_session = secrets.token_hex(16)
            self.public_transport_state = None

    def enroll(self, group):
        response=self._request(ENROLL_ROUTE.removeprefix('/api/'),{
            'host_id':group['host_id'], 'enrollment_token':group['enrollment_token'],
            'device_token':self.access_token,
        },use_lobby_token=False)
        identity=response.get('device_id')
        if (set(response)!={'registered','device_id'} or response['registered'] is not True
                or type(identity) is not int or not 1<=identity<=MAX_DEVICES):
            raise CommunityError('The host returned an invalid registration receipt.')
        return identity

    def _validated_target(self,match,name,*,spectator=False,public=False,existing_only=False):
        first, last = self.connection['first_udp_port'], self.connection['last_udp_port']
        allowed_ports = (range(first, last + 1),)
        # Stock invitations survive capacity increases and migration between the
        # two Friend Host ranges. Custom ranges keep their original bounds.
        if first in MATCH_UDP_BASES and last < first + MATCH_SLOT_LIMIT:
            allowed_ports = tuple(range(base, base + MATCH_SLOT_LIMIT) for base in MATCH_UDP_BASES)
        if (not isinstance(match, dict) or match.get('address') != self.server_address
                or type(match.get('port')) is not int
                or not any(match['port'] in ports for ports in allowed_ports)):
            raise CommunityError('The public match endpoint differs from this invitation.')
        grant=match.get('udpGrant')
        native=dict(match,address='127.0.0.1',port=DIRECT_BRIDGE_POLICY['first_port'])
        target=super()._validated_target(native,name,spectator=spectator)
        if (not isinstance(grant,dict) or grant.get('matchId')!=target['matchId']
                or grant.get('port')!=match['port'] or not isinstance(grant.get('id'),str)):
            raise CommunityError('Match admission is unavailable. Wait for the host to start the match and try again.')
        key=(grant.get('matchId'),grant.get('id'))
        with self.lock:
            proxy=self.proxies.get(key)
            if proxy is not None and proxy.grant!=grant:
                try:
                    if not public:
                        raise ValueError('Unexpected renewal')
                    proxy.renew(grant)
                except ValueError as exc:
                    raise CommunityError('UDP admission changed without a new identity.') from exc
            if proxy is None:
                if existing_only:
                    return None
                # One native session at a time is already enforced by CommunityGame.
                for old in self.proxies.values():old.close()
                self.proxies.clear()
                try:proxy=UdpClient(self.server_address,grant)
                except (TypeError,ValueError,OSError)as exc:raise CommunityError('UDP match admission could not be opened.')from exc
                self.proxies[key]=proxy
            return dict(target,endpoint='127.0.0.1:'+str(proxy.port))

    def close(self):
        with self.lock:
            for proxy in self.proxies.values():proxy.close()
            self.proxies.clear()

def group_connection(root, local, *, ssl_context=None, test_source=None):
    test=test_source is not None
    group=validate_group(read_json(root/GROUP_FILE,16384),local_test=test)
    path=local/'hosts'/(group['host_id']+'.json')
    with locked_state(path):
        if path.exists():
            state=read_json(path,16384)
        else:
            # Commit the token before the first network call so retries reuse it.
            state={'access_token':secrets.token_urlsafe(32),'device_id':None}
            write_json(path,state)
        if not isinstance(state,dict) or set(state)!={'access_token','device_id'}:
            raise ValueError('Invalid saved Direct Starter registration.')
        identity=state['device_id']
        if identity is not None and (type(identity) is not int or not 1<=identity<=MAX_DEVICES):
            raise ValueError('Invalid saved Direct Starter device ID.')
        connection=validate_connection(dict(validate_endpoint(group,local_test=test),format=1,
                                             access_token=state['access_token']),local_test=test)
        if identity is None:
            client=DirectClient(connection,ssl_context=ssl_context,test_source=test_source)
            state['device_id']=client.enroll(group)
            write_json(path,state)
        return connection


class ArmorPanel:
    classes = ('Light', 'Medium', 'Heavy')

    def __init__(self, tk, desktop, lobby):
        from tkinter import ttk
        from desktop_launcher import BG, MUTED, PANEL

        self.tk, self.desktop, self.lobby = tk, desktop, lobby
        self.results = queue.Queue()
        self.catalog = {}
        self.saved = {}
        self.previews = {}
        self.requests = set()
        self.weight = tk.StringVar(value=self.classes[0])
        self.suit = tk.StringVar()
        self.status = tk.StringVar()
        self.caption = tk.StringVar()
        self.panel = tk.Frame(desktop.root, bg=BG)
        desktop.label(self.panel, 'Armor', 27, True).pack(anchor='w')
        desktop.label(self.panel, 'Choose a suit for each armor class.', color=MUTED).pack(anchor='w', pady=(4, 18))
        row = tk.Frame(self.panel, bg=BG)
        row.pack(anchor='w')
        self.weight_box = ttk.Combobox(row, textvariable=self.weight, values=self.classes, state='readonly', width=12)
        self.weight_box.pack(side='left')
        self.weight_box.bind('<<ComboboxSelected>>', self.select_class)
        self.suit_box = ttk.Combobox(row, textvariable=self.suit, state='disabled', width=25)
        self.suit_box.pack(side='left', padx=(8, 0))
        self.suit_box.bind('<<ComboboxSelected>>', self.select_suit)
        preview = tk.Frame(self.panel, bg=PANEL, width=460, height=335)
        preview.pack(anchor='w', pady=(12, 4), fill='x')
        preview.pack_propagate(False)
        self.image = tk.Label(preview, bg=PANEL, fg=MUTED)
        self.image.pack(fill='both', expand=True)
        tk.Label(self.panel, textvariable=self.caption, bg=BG, fg=MUTED).pack(anchor='w')
        self.save = desktop.button(self.panel, 'Save armor choices', self.save_choices)
        self.save.pack(anchor='w', pady=(10, 0))
        self.save.configure(state='disabled')
        tk.Label(self.panel, textvariable=self.status, bg=BG, fg=MUTED, wraplength=530,
                 justify='left').pack(anchor='w', pady=(6, 0))
        desktop.button(desktop.sidebar, 'Armor', lambda: desktop.show_panel('armor'), False).pack(
            fill='x', padx=18, pady=(6, 0))

    def submit(self, key, **data):
        if key in self.requests:
            return
        self.requests.add(key)

        def run():
            try:
                self.results.put((key, self.lobby.armor_suits(**data), None))
            except CommunityError as exc:
                self.results.put((key, None, str(exc)))

        threading.Thread(target=run, daemon=True).start()
        if len(self.requests) == 1:
            self.desktop.root.after(80, self.tick)

    def open(self):
        if not self.catalog:
            self.status.set('Loading available suits…')
            self.submit('load')
        elif self.current_selection() not in self.previews:
            self.select_suit()

    def current_selection(self):
        weight = self.weight.get()
        suit = self.selected.get(weight) if self.catalog else None
        return weight, suit

    def select_class(self, _event=None):
        if self.catalog:
            weight, suit = self.current_selection()
            options = self.catalog[weight]
            self.suit_box.configure(values=list(options.values()), state='readonly')
            self.suit.set(options[suit])
            self.select_suit()

    def select_suit(self, _event=None):
        weight = self.weight.get()
        suit = next(key for key, label in self.catalog[weight].items() if label == self.suit.get())
        self.selected[weight] = suit
        key = (weight, suit)
        self.caption.set(f'{weight} armor · {self.suit.get()}')
        self.image.configure(image=self.previews.get(key, ''), text='')
        if key not in self.previews:
            self.image.configure(text='Loading suit preview…')
            self.submit(key, weight=weight, suit=suit)
        self.refresh_save()

    def refresh_save(self):
        self.save.configure(state='normal' if self.selected != self.saved and 'save' not in self.requests else 'disabled')

    def save_choices(self):
        self.submit('save', choices=dict(self.selected))
        self.status.set('Saving armor choices…')
        self.refresh_save()

    def load_choices(self, response):
        catalog, choices = response.get('catalog'), response.get('choices')
        if not isinstance(catalog, dict) or not isinstance(choices, dict):
            raise ValueError('The host returned an invalid armor catalog.')
        for weight in self.classes:
            options = catalog.get(weight)
            suit = choices.get(weight)
            if (not isinstance(options, dict) or type(suit) is not str or suit not in options
                    or any(type(label) is not str or not label or len(label) > 80 for label in options.values())
                    or len(set(options.values())) != len(options)):
                raise ValueError('The host returned an invalid armor catalog.')
        self.catalog = catalog
        self.saved = dict(choices)
        self.selected = dict(choices)
        self.status.set('')
        self.select_class()

    def tick(self):
        if self.desktop.closing:
            return
        while not self.results.empty():
            key, response, error = self.results.get_nowait()
            try:
                if error:
                    raise ValueError(error)
                if key == 'load':
                    self.load_choices(response)
                elif key == 'save':
                    saved = response.get('choices')
                    if not isinstance(saved, dict) or set(saved) != set(self.classes) or any(
                            type(saved[weight]) is not str or saved[weight] not in self.catalog[weight] for weight in self.classes):
                        raise ValueError('The host did not confirm your armor choices.')
                    self.saved = saved
                    self.status.set('Armor choices saved. They apply the next time you spawn.')
                else:
                    image = self.tk.PhotoImage(data=response.get('preview', ''), format='png')
                    if image.height() > 315:
                        image = image.subsample(2)
                    self.previews[key] = image
                    if key == self.current_selection():
                        self.image.configure(image=image, text='')
            except (ValueError, self.tk.TclError) as exc:
                if isinstance(key, tuple):
                    if key == self.current_selection():
                        self.image.configure(image='', text='Preview unavailable. Select the suit again to retry.')
                else:
                    self.status.set(str(exc))
            finally:
                self.requests.remove(key)
                if self.catalog:
                    self.refresh_save()
        if self.requests:
            self.desktop.root.after(80, self.tick)


class PublicCTFPanel:
    def __init__(self, tk, desktop, lobby):
        from desktop_launcher import BG, MUTED
        self.tk, self.desktop, self.lobby = tk, desktop, lobby
        self.root = desktop.root
        self.results = queue.Queue()
        self.pending = set()
        self.poll_at = 0
        self.ballot = None
        self.ballot_key = None
        self.state = {}
        self.status = tk.StringVar(value='Checking the public server…')
        self.format_label = tk.StringVar(value='Bots fill open slots')
        self.panel = tk.Frame(self.root, bg=BG)
        desktop.label(self.panel, 'Public CTF', 27, True).pack(anchor='w')
        tk.Label(self.panel, textvariable=self.format_label, bg=BG, fg=MUTED).pack(anchor='w', pady=(4, 18))
        tk.Label(self.panel, textvariable=self.status, bg=BG, fg=MUTED, wraplength=580,
                 justify='left').pack(anchor='w', pady=(0, 12))
        actions = tk.Frame(self.panel, bg=BG)
        actions.pack(anchor='w')
        self.join = desktop.button(actions, 'Join Public CTF', self.start)
        self.join.pack(side='left')
        self.leave = desktop.button(actions, 'Leave game', self.stop, False)
        self.leave.pack(side='left', padx=(8, 0))
        self.nav = desktop.button(desktop.sidebar, 'Public CTF', lambda: desktop.show_panel('public'), False)
        self.nav.pack(fill='x', padx=18, pady=(6, 0))
        if lobby.public_only:
            desktop.lobbies_nav.pack_forget()
            desktop.live_nav.pack_forget()
        desktop.show_panel('public')
        self.root.after(150, self.tick)

    def submit(self, action, work):
        if action in self.pending:
            return
        self.pending.add(action)

        def run():
            try:
                self.results.put((action, work(), None))
            except Exception as exc:
                self.results.put((action, None, str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def start(self):
        ui = self.desktop
        if not ui.game:
            ui.game = ui.game_factory(self.lobby)
        name = ui.name.get().strip()
        self.status.set('Reserving a seat…')
        self.submit('start', lambda: ui.game.start_public(name))

    def stop(self):
        if self.desktop.game:
            self.desktop.game.stop()

    def refresh_ballot(self, state, active):
        if state.get('phase') != 'voting' or not state.get('team') or not active:
            if self.ballot is not None:
                self.ballot.destroy()
                self.ballot = None
            self.ballot_key = None
            return
        round_id = state['round']
        key = (round_id, state['seconds'], state['selected'],
               tuple((option['id'], option['votes']) for option in state['options']))
        if self.ballot is None:
            self.ballot = self.tk.Toplevel(self.root)
            self.ballot.title('Vote for the next map')
            self.ballot.attributes('-topmost', True)
            self.ballot.resizable(False, False)
            self.ballot.protocol('WM_DELETE_WINDOW', self.ballot.withdraw)
            self.ballot_message = self.tk.StringVar()
            self.tk.Label(self.ballot, textvariable=self.ballot_message, padx=24, pady=12).pack()
            self.ballot_buttons = {}
            for option in state['options']:
                map_id = option['id']
                button = self.tk.Button(self.ballot, width=32, pady=6,
                    command=lambda choice=map_id: self.submit('vote', lambda: self.lobby.public_vote(round_id, choice)))
                button.pack(padx=20, pady=(0, 8))
                self.ballot_buttons[map_id] = button
        if self.ballot_key != key:
            self.ballot_key = key
            self.ballot_message.set(f'Next map · {state["seconds"]} seconds left')
            for option in state['options']:
                prefix = '✓ ' if state['selected'] == option['id'] else ''
                self.ballot_buttons[option['id']].configure(text=f'{prefix}{option["label"]} ({option["votes"]})')

    def tick(self):
        ui = self.desktop
        if ui.closing:
            return
        game = ui.game
        active = ui.game_status not in ('idle', 'stopped', 'finished', 'failed')
        public = active and game is not None and game.role == 'public'
        try:
            while True:
                action, state, error = self.results.get_nowait()
                self.pending.discard(action)
                if error:
                    self.status.set(error)
                elif isinstance(state, dict):
                    self.state = state
                    label = self.lobby.map_label(state['map']) or state['map']
                    phase = state['phase']
                    summary = {'loading': 'Preparing the server', 'playing': label,
                               'voting': 'Voting for the next map', 'traveling': 'Loading the next map'}[phase]
                    team_size = state.get('teamSize', 12)
                    if type(team_size) is not int or not 1 <= team_size <= 64:
                        team_size = 12
                    self.format_label.set(f'{team_size} vs. {team_size} · Bots fill open slots')
                    self.status.set(state.get('error') or f'{summary} · {state["players"]}/{2 * team_size} players')
        except queue.Empty:
            pass
        state = self.state
        if public and ui.game_status != 'playing':
            self.status.set(ui.status.get())
        can_join = state.get('phase') == 'playing' and not active and 'start' not in self.pending
        self.join.configure(state='normal' if can_join else 'disabled')
        self.leave.configure(state='normal' if public else 'disabled')
        self.refresh_ballot(state, public and ui.game_status == 'playing')
        now = time.monotonic()
        if now >= self.poll_at and (public or ui.current_panel == 'public'):
            self.poll_at = now + 2
            self.submit('poll', lambda: self.lobby.public_state(renew=public))
        self.root.after(150, self.tick)

def main(root=ROOT, *, on_ready=None):
    import tkinter as tk
    from tkinter import filedialog,messagebox
    from desktop_launcher import Desktop
    from community_game import CommunityGame
    from startup_paths import installation_options
    from client_support import discover_game
    from map_sync import MapSync
    from steam_identity import read_steam_name
    local=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'Tribes3DirectStarter'
    local.mkdir(parents=True,exist_ok=True);saved=local/'connection.json'
    chooser=tk.Tk();chooser.withdraw()
    lobby=None
    try:
        try:
            game,workspace=installation_options();source=discover_game(game)
        except RuntimeError as exc:
            # Steam discovery reports a missing or ambiguous game as RuntimeError.
            raise ValueError(str(exc)) from exc
        if (root/GROUP_FILE).exists():
            connection=group_connection(root,local)
        else:
            if not saved.exists():
                filename=filedialog.askopenfilename(title='Choose the player invitation JSON sent by your host',filetypes=[('Player invitation','*.json')])
                if filename:
                    write_json(saved,validate_connection(read_json(filename,16384)))
            connection=validate_connection(read_json(saved,16384)) if saved.exists() else None
        if connection is not None:
            lobby=DirectClient(connection, proximity_settings=local/'proximity-voice.json')
            try:lobby.capabilities()
            except CommunityError:
                lobby.close()
                lobby=None
                messagebox.showerror('Direct host connection','Could not open the lobby. Ask the host to check your access, certificate and TCP forwarding.')
    except (OSError, ValueError, CommunityError) as exc:
        if lobby is not None:
            lobby.close()
        lobby=None
        messagebox.showerror('Direct Starter setup',str(exc))
    finally:chooser.destroy()
    if lobby is None:
        # A canceled invitation or unreachable host does not invalidate the update.
        if on_ready is not None:
            on_ready()
        return
    class DirectDesktop(Desktop):
        public_panel = None
        armor_panel = None

        def show_panel(self, name):
            if self.closing:
                return
            if self.armor_panel is not None:
                self.armor_panel.panel.pack_forget()
            if self.public_panel is not None:
                self.public_panel.panel.pack_forget()
            if name == 'armor' and self.armor_panel is not None:
                self.current_panel = 'armor'
                self.lobby_panel.pack_forget()
                self.live_panel.pack_forget()
                self.armor_panel.panel.pack(side='left', fill='both', expand=True, padx=32, pady=28)
                self.armor_panel.open()
                return
            if self.public_panel is not None:
                if name == 'public' or lobby.public_only:
                    self.current_panel = 'public'
                    self.lobby_panel.pack_forget()
                    self.live_panel.pack_forget()
                    self.public_panel.panel.pack(side='left', fill='both', expand=True, padx=32, pady=28)
                    return
            super().show_panel(name)

        def close(self):
            try:super().close()
            finally:lobby.close()

    class DirectGame(CommunityGame):
        def start_public(self, name):
            try:
                status = self._start(public_name=name)
            except Exception:
                if self.role == 'public' and self.status == 'failed':
                    self.release_public()
                raise
            if status == 'stopped':
                self.release_public()
            return status

        def release_public(self):
            try:
                lobby.public_leave()
            except CommunityError:
                pass  # The host also releases expired seats and disconnected clients.

        def _run(self, argv, artifacts):
            def ready_run():
                with self.lock:
                    return self.run if self.status == 'playing' else None

            if self.role == 'player':
                with lobby.proximity_game(ready_run):
                    super()._run(argv, artifacts)
            elif self.role == 'public':
                try:
                    super()._run(argv, artifacts)
                finally:
                    self.release_public()
            else:
                super()._run(argv, artifacts)

    try:
        window=tk.Tk();window.title('TRIBES 3 — Direct Host Starter')
        map_sync=MapSync(lobby,root,workspace)
        factory=lambda current:DirectGame(current,root,source,workspace,workspace/'direct-desktop-control',map_sync=map_sync)
        gui=DirectDesktop(window,lobby,factory,
                          steam_name_loader=lambda:read_steam_name(source,root/'base-game-manifest.json'),
                          map_sync=map_sync)
        if lobby.public_supported:
            gui.public_panel = PublicCTFPanel(tk, gui, lobby)
            gui.show_panel('public' if lobby.public_only else 'lobbies')
        if lobby.armor_supported:
            gui.armor_panel = ArmorPanel(tk, gui, lobby)
        if lobby.proximity_supported:
            enabled = tk.BooleanVar(value=lobby.proximity_enabled.is_set())
            tk.Checkbutton(gui.sidebar, text='Proximity voice', variable=enabled,
                           command=lambda: lobby.set_proximity_voice(enabled.get()),
                           bg='#0d1927', fg='#eff7ff', activebackground='#0d1927',
                           activeforeground='#eff7ff', selectcolor='#20374a').pack(anchor='w', padx=20, pady=(18, 0))
            key_label = tk.StringVar(value=f'Change key ({PTT_KEY_NAMES[lobby.proximity_key]})')
            change_key = gui.button(gui.sidebar, 'Change proximity key',
                                    lambda: choose_proximity_key(window, lobby.bind_proximity_key), False)
            change_key.configure(textvariable=key_label)
            change_key.pack(anchor='w', padx=24, pady=(2, 4))
            indicator = tk.StringVar(value=lobby.proximity_status)
            tk.Label(gui.sidebar, textvariable=indicator, bg='#0d1927', fg='#9fb3c6',
                     wraplength=170, justify='left').pack(anchor='w', padx=24)

            def refresh_voice():
                key_label.set(f'Change key ({PTT_KEY_NAMES[lobby.proximity_key]})')
                indicator.set(lobby.proximity_status)
                if not gui.closing:
                    window.after(150, refresh_voice)

            window.after(150, refresh_voice)
        window.protocol('WM_DELETE_WINDOW',gui.close)
        if on_ready is not None:
            window.update_idletasks()
            on_ready()
        window.mainloop()
    finally:
        lobby.close()

def change_invitation():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    try:
        if (ROOT/GROUP_FILE).exists():
            messagebox.showinfo('Group Starter','This Starter uses its bundled host. To switch hosts, open the Starter ZIP prepared by the other host.')
            return
        filename=filedialog.askopenfilename(title='Choose the new player invitation',filetypes=[('Player invitation','*.json')])
        if filename:
            d=validate_connection(read_json(filename,16384));p=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'Tribes3DirectStarter/connection.json'
            write_json(p,d);messagebox.showinfo('Invitation saved','Close any other Direct Starter window, then reopen Direct Starter.')
    except Exception as exc:messagebox.showerror('Invitation',str(exc))
    finally:root.destroy()

if __name__=='__main__':main()
