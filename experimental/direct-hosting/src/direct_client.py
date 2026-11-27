"""Separate direct-host Starter entry with local per-device credentials."""
from collections import deque
from contextlib import closing, contextmanager
import ctypes as C
from ctypes import wintypes as W
import hashlib
import http.client
import json
import os
import pathlib
import queue
import re
import secrets
import shutil
import socket
import ssl
import tempfile
import threading
import time
from direct_network import (ENDPOINT_FIELDS, ENROLL_ROUTE, GROUP_FILE, MATCH_SLOT_LIMIT, MATCH_UDP_BASES,
                            MAX_DEVICES, TOKEN, UdpClient,
                            VoiceFrames, VOICE_AUDIO, VOICE_FRAME_BYTES, VOICE_KEEPALIVE, VOICE_PROTOCOL,
                            VOICE_RELEASE, VOICE_ROUTE, VOICE_SAMPLE_RATE,
                            locked_state, read_json, valid_public_address, validate_endpoint, validate_group, write_json)
from direct_network import TOOL_TIPS_ROUTE, TOOL_TIPS_LIMIT, decode_tool_tips
from community_transport import (CommunityClient, CommunityConnectionError, CommunityError, PinnedHTTPSConnection,
                                 validated_projectile_settings)
from community_game import CommunityGame
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
        if pathlib.Path(record['argv'][0]) != executable:
            from client_preparation import stable_session_executable
            executable = stable_session_executable(ROOT, run, record)
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
        return self.foreground_window() is not None

    def foreground_window(self):
        window = self.user.GetForegroundWindow()
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(window, C.byref(pid))
        return window if pid.value == self.pid and self.alive() else None

    def foreground_bounds(self):
        window = self.foreground_window()
        if window is None:
            return None
        self.user.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        self.user.GetWindowRect.restype = W.BOOL
        rect = W.RECT()
        if self.user.GetWindowRect(window, C.byref(rect)) and rect.right > rect.left and rect.bottom > rect.top:
            return rect.left, rect.top, rect.right, rect.bottom

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
    local_host = False

    @staticmethod
    def accepts_server_address(address):
        return address.is_global and not address.is_multicast

    def __init__(self,connection,*,ssl_context=None,test_source=None,proximity_settings=None):
        d=validate_connection(connection,local_test=self.local_host or test_source is not None)
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
        self.pug_supported = False
        self.public_transport_state = None

    def capabilities(self):
        caps = super().capabilities()
        self.proximity_supported = os.name == 'nt' and caps.get('proximityVoice') == VOICE_PROTOCOL
        self.public_supported = caps.get('publicCTF') is True
        self.public_only = self.public_supported and caps.get('publicOnly') is True
        self.armor_supported = caps.get('armorSuits') == 1
        self.pug_supported = caps.get('rankedPug') == 1 and not self.public_only
        return caps

    def armor_suits(self, **data):
        return self._request('armor-suits', data, use_lobby_token=False)

    def pug(self, action, **data):
        response = self._request('pug-' + action, data, use_lobby_token=False)
        if action == 'stats':
            return response
        state = response.get('pug')
        if not isinstance(state, dict) or state.get('requiredPlayers') != 14:
            raise CommunityError('The host returned invalid ranked PUG status.')
        return state

    def pug_target(self, room_id, game):
        response = self._request('pug-target', {'room': room_id}, use_lobby_token=False)
        target = response.get('target')
        return self._validated_target(target, game['map'])

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
                return {'map': map_id, 'contentHash': fingerprint,
                        **({'manifestHash': state['manifestHash']} if 'manifestHash' in state else {})}
            if time.monotonic() >= deadline:
                raise CommunityError(state.get('error') or 'Public CTF is preparing the next map. Try joining again.')
            time.sleep(2)

    def public_state(self, *, renew=False):
        state = self._public('state')
        if renew:
            with self.lock:
                previous = self.public_transport_state
                # The next round gets a fresh native session and UDP grant.
                if previous == (state.get('id'), state.get('round')) and state.get('target'):
                    self._validated_target(state['target'], state.get('map'), public=True, existing_only=True)
        return state

    def public_target(self):
        deadline = time.monotonic() + 45
        while True:
            state = self.public_state()
            if state.get('target'):
                with self.lock:
                    target = self._validated_target(state['target'], state.get('map'), public=True)
                    self.public_transport_state = (state['id'], state['round'])
                    return dict(target, publicRound=self.public_transport_state)
            if not state.get('team') or time.monotonic() >= deadline:
                raise CommunityError(state.get('error') or 'Your public match seat was not ready. Try joining again.')
            time.sleep(1)

    def public_projectile_settings(self, match_id, round_id, settings):
        with self.lock:
            response = self._request('public-projectile-settings', {
                'matchId': match_id, 'round': round_id, 'settings': validated_projectile_settings(settings),
            }, use_lobby_token=False)
            if type(response.get('round')) is not int or response['round'] != round_id:
                raise CommunityError('The projectile settings belong to another public round.')
            return self._projectile_reply(response, match_id)

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
        if not self.proximity_supported or admission is None or self.test_source or getattr(proxy, 'community_host', False):
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
            'X-Community-Host': '1',
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
        if not self.local_host and first in MATCH_UDP_BASES and last < first + MATCH_SLOT_LIMIT:
            allowed_ports = tuple(range(base, base + MATCH_SLOT_LIMIT) for base in MATCH_UDP_BASES)
        remote = isinstance(match, dict) and match.get('communityHost') is True and not public and not spectator
        if remote:
            if self.local_host:
                raise CommunityError('This local host cannot hand off to another server.')
            try:
                address = valid_public_address(match['address'], local_test=bool(self.test_source))
                if type(match.get('port')) is not int or not 1024 <= match['port'] <= 65535:
                    raise ValueError('Invalid community host port')
            except (TypeError, ValueError, KeyError) as exc:
                raise CommunityError('The lobby returned an invalid community host endpoint.') from exc
        elif (not isinstance(match, dict) or match.get('address') != self.server_address
              or type(match.get('port')) is not int
              or not any(match['port'] in ports for ports in allowed_ports)):
            raise CommunityError('The public match endpoint differs from this invitation.')
        else:
            address = self.server_address
        grant=match.get('udpGrant')
        native=dict(match,address='127.0.0.1',port=DIRECT_BRIDGE_POLICY['first_port'])
        target=super()._validated_target(native,name,spectator=spectator)
        if (not isinstance(grant,dict) or grant.get('matchId')!=target['matchId']
                or grant.get('port')!=match['port'] or not isinstance(grant.get('id'),str)):
            raise CommunityError('Match admission is unavailable. Wait for the host to start the match and try again.')
        key=(grant.get('matchId'),grant.get('id'))
        with self.lock:
            proxy=self.proxies.get(key)
            if proxy is not None and remote and proxy.remote != (address, match['port']):
                raise CommunityError('The community host endpoint changed during admission.')
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
                try:proxy=UdpClient(address,grant)
                except (TypeError,ValueError,OSError)as exc:raise CommunityError('UDP match admission could not be opened.')from exc
                proxy.community_host = remote
                self.proxies[key]=proxy
            return dict(target,endpoint='127.0.0.1:'+str(proxy.port))

    def close(self):
        with self.lock:
            for proxy in self.proxies.values():proxy.close()
            self.proxies.clear()

class LocalDirectClient(DirectClient):
    """A private Starter-owned connection with its own trust and device identity."""

    local_host = True
    address_error = 'Local Play must use the loopback address.'

    @staticmethod
    def accepts_server_address(address):
        return str(address) == '127.0.0.1'

    def __init__(self, session, *, proximity_settings=None):
        session = pathlib.Path(session).resolve(strict=True)
        path = session/'connection.json'
        certificate = session/'local-host.pem'
        if path.resolve(strict=True) != path or certificate.resolve(strict=True) != certificate:
            raise ValueError('Invalid Local Play session files.')
        connection = validate_connection(read_json(path, 16384), local_test=True)
        if (connection['hostname'] != 'localhost' or connection['public_address'] != '127.0.0.1'
                or connection['https_port'] < 1024 or connection['first_udp_port'] != connection['last_udp_port']):
            raise ValueError('Invalid Local Play host identity.')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=str(certificate))
        context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
        super().__init__(connection, ssl_context=context, proximity_settings=proximity_settings)


class LocalHostSession:
    """Own the local lobby service and all children it starts."""
    def __init__(self, package, source, workspace):
        self.package = package.resolve(strict=True)
        self.runtime = self.package/'local-host'
        self.source = source.resolve(strict=True)
        self.workspace = workspace.resolve()
        self.thread = None
        self.session = None
        self.client = None
        self.result = None
        self.error = None
        self.stop_requested = threading.Event()

    @property
    def available(self):
        return (os.name == 'nt' and (self.runtime/'operator/direct_service.py').is_file()
                and (self.runtime/'host/package-manifest.json').is_file()
                and (self.package/'python/python.exe').is_file())

    def verify_runtime(self):
        from verified_file_cache import verify_package

        package = verify_package(self.package)
        rows = {row['path'] for row in package['files']}
        expected = {name for name in rows if name.startswith('local-host/')}
        actual = {path.relative_to(self.package).as_posix()
                  for path in self.runtime.rglob('*') if path.is_file()}
        if (expected != actual
                or not {'local-host/operator/direct_service.py', 'local-host/host/package-manifest.json',
                        'local-host/shared-content.json', 'python/python.exe'} <= rows):
            raise CommunityError('Local Play files differ from the verified Starter package.')
        layout = read_json(self.runtime/'shared-content.json', 2*1024**2)
        from map_sync_contract import COOKED_PATH
        paths = layout.get('paths') if isinstance(layout, dict) else None
        if (not isinstance(paths, list) or set(layout) != {'format', 'paths'} or layout['format'] != 1
                or any(not isinstance(name, str) or not COOKED_PATH.fullmatch(name)
                       or name not in rows for name in paths)
                or len(paths) != len(set(paths))):
            raise CommunityError('Local Play has an invalid shared map inventory.')
        return actual, paths

    def stage_runtime(self, staging, files, shared):
        def place(source, destination):
            if destination.exists():
                raise CommunityError('Duplicate Local Play staged file.')
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source, destination)
            except OSError:
                shutil.copyfile(source, destination)

        for name in sorted(files):
            place(self.package/name, staging/name.removeprefix('local-host/'))
        for name in shared:
            place(self.package/name, staging/'host'/name)

    def start(self):
        if not self.available:
            raise CommunityError('Local Play is unavailable in this Starter package.')
        if self.thread is not None:
            raise CommunityError('Stop the current local host before starting another.')
        from owned_native_session import run_owned_job

        files, shared = self.verify_runtime()
        if self.stop_requested.is_set():
            raise CommunityError('The local host was stopped.')
        owner_root = self.workspace/'local-host'
        owner_root.mkdir(parents=True, exist_ok=True)
        run = pathlib.Path(tempfile.mkdtemp(prefix='local-', dir=owner_root))
        self.session = run/'session'
        self.session.mkdir()
        self.cancel_path = run/'cancel.json'
        staging = run/'runtime'

        def discard_staging():
            if staging.resolve().parent == run.resolve() and staging.name == 'runtime':
                shutil.rmtree(staging, ignore_errors=True)

        try:
            self.stage_runtime(staging, files, shared)
            if self.stop_requested.is_set():
                raise CommunityError('The local host was stopped.')
        except Exception:
            discard_staging()
            raise
        script = staging/'operator/direct_service.py'
        # The bundled Python uses an isolated ._pth file. Add just the
        # packaged operator directory before running its normal entry point.
        bootstrap = ('import pathlib, runpy, sys; '
                     'sys.argv = sys.argv[1:]; '
                     'sys.path.insert(0, str(pathlib.Path(sys.argv[0]).parent)); '
                     'runpy.run_path(sys.argv[0], run_name="__main__")')
        command = [
            str(self.package/'python/python.exe'), '-B', '-u', '-c', bootstrap, str(script),
            '--local-session', str(self.session), '--local-game', str(self.source),
            '--local-workspace', str(owner_root/'game-staging'),
        ]

        def own():
            try:
                self.result = run_owned_job(command, staging, dict(os.environ),
                                            run/'owner', budget=None, cancellation_path=self.cancel_path)
            except (OSError, ValueError) as exc:
                self.error = str(exc)
            finally:
                discard_staging()
                for name in ('connection.json', 'local-host-key.pem'):
                    try:
                        (self.session/name).unlink(missing_ok=True)
                    except OSError:
                        pass

        self.thread = threading.Thread(target=own, name='Local Play host')
        self.thread.start()
        try:
            deadline = time.monotonic()+900
            while time.monotonic() < deadline:
                if self.stop_requested.wait(0.15):
                    raise CommunityError('The local host was stopped.')
                status_path = self.session/'status.json'
                status = read_json(status_path, 16384) if status_path.is_file() else {}
                if status.get('status') == 'failed':
                    raise CommunityError(status.get('message') or 'The local host could not start.')
                if self.error is not None or not self.thread.is_alive():
                    raise CommunityError(self.error or 'The local host exited during startup.')
                if status.get('status') == 'ready':
                    client = LocalDirectClient(self.session)
                    try:
                        caps = client.capabilities()
                        if self.stop_requested.is_set():
                            raise CommunityError('The local host was stopped.')
                    except (OSError, ValueError, CommunityError):
                        client.close()
                        raise
                    self.client = client
                    return client, caps
            raise CommunityError('Local host startup timed out while verifying the game package.')
        except (OSError, ValueError, CommunityError):
            self.stop()
            raise

    def stop(self):
        self.stop_requested.set()
        if self.client is not None:
            self.client.close()
        thread = self.thread
        if thread is None or not thread.is_alive():
            return
        # Write the stop request even if the service has not opened HTTPS.
        # The owner only cancels its own Job if graceful cleanup stalls.
        write_json(self.session/'stop.json', {'stop': True})
        thread.join(45)
        if thread.is_alive():
            write_json(self.cancel_path, {'cancel': True, 'reason': 'Requested Local Play shutdown'})
            thread.join(10)
        if thread.is_alive():
            raise CommunityError('The local host is still closing.')


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


ARMOR_MODEL_BLOBS = {}


def download_armor_model(lobby, key):
    import lzma
    from armor_viewport import decode_model
    from direct_update_contract import ROUTE

    size, chunks = ARMOR_MODEL_BLOBS[key]
    compressed = bytearray()
    try:
        for digest, length in chunks:
            with closing(PinnedHTTPSConnection(lobby.hostname,lobby.port,lobby.server_address,
                                               context=lobby.context,timeout=8)) as connection:
                authority = f'{lobby.hostname.lower()}:{lobby.port}'
                connection.request('GET', ROUTE+'starter-file-'+digest+'.bin', headers={'Host':authority})
                response = connection.getresponse()
                if response.status != 200:
                    raise ValueError('The 3D model is unavailable from this host.')
                data = response.read(length+1)
                if len(data)!=length or hashlib.sha256(data).hexdigest()!=digest:
                    raise ValueError('The downloaded 3D model did not match the signed release.')
                compressed.extend(data)
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=32*1024*1024)
        raw = decoder.decompress(compressed,max_length=size+1)
        if len(raw)!=size or not decoder.eof or decoder.unused_data:
            raise ValueError('Invalid 3D model data.')
        model = decode_model(raw)
        if model.texture is None:
            raise ValueError('The 3D model is missing its suit texture.')
        return model
    except (OSError, http.client.HTTPException, ValueError, lzma.LZMAError) as exc:
        raise CommunityError(str(exc)) from exc


class ArmorPanel:
    classes = ('Light', 'Medium', 'Heavy')

    def __init__(self, tk, desktop, lobby, *, model_directory=None):
        from tkinter import ttk
        from desktop_launcher import BG, MUTED, PANEL

        self.tk, self.desktop, self.lobby = tk, desktop, lobby
        self.results = queue.Queue()
        self.catalog = {}
        self.saved = {}
        self.requests = set()
        self.models = {}
        self.model_directory = model_directory
        self.viewport = None
        self.displayed_model = None
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
        self.model_status = tk.Label(preview, text='Loading available suits…', bg=PANEL, fg=MUTED)
        self.model_status.pack(fill='both', expand=True)
        self.model_frame = tk.Frame(preview, bg=PANEL, takefocus=True, cursor='fleur')
        self.orbit_help = desktop.label(self.panel, 'Drag to rotate · Scroll to zoom · Home to reset', color=MUTED)
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
                response = download_armor_model(self.lobby,key) if isinstance(key,tuple) else self.lobby.armor_suits(**data)
                self.results.put((key, response, None))
            except CommunityError as exc:
                self.results.put((key, None, str(exc)))

        threading.Thread(target=run, daemon=True).start()
        if len(self.requests) == 1:
            self.desktop.root.after(80, self.tick)

    def open(self):
        if not self.catalog:
            self.status.set('Loading available suits…')
            self.submit('load')
        elif self.current_selection() != self.displayed_model:
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
        if key != self.displayed_model and not self.show_model(key):
            self.displayed_model = None
            self.model_frame.pack_forget()
            self.orbit_help.pack_forget()
            loading = os.name=='nt' and key in ARMOR_MODEL_BLOBS and key not in self.models
            self.model_status.configure(text='Loading 3D suit…' if loading else '3D model unavailable for this suit.')
            self.model_status.pack(fill='both', expand=True)
            if loading:
                self.submit(key)
        self.refresh_save()

    def show_model(self, key):
        if os.name != 'nt':
            return False
        weight, suit = key
        if not re.fullmatch(r'[a-z0-9-]{1,48}', suit):
            return False
        try:
            model = self.models.get(key)
            if model is None:
                if self.model_directory is None:
                    return False
                from armor_viewport import read_model
                path = self.model_directory / f'{weight.lower()}-{suit}.t3m'
                model = read_model(path)
            if model.texture is None:
                return False
            self.present_model(model)
        except (ImportError, OSError, ValueError, self.tk.TclError):
            return False
        self.displayed_model = key
        return True

    def present_model(self, model):
        from armor_viewport import ArmorViewport
        if self.viewport is None:
            self.viewport = ArmorViewport(self.model_frame)
        self.model_status.pack_forget()
        self.model_frame.pack(fill='both', expand=True)
        self.viewport.show(model)
        self.orbit_help.pack(anchor='w', before=self.save)

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
                    if len(self.models)>=3:
                        self.models.pop(next(iter(self.models)))
                    self.models[key] = response
                    if key==self.current_selection() and not self.show_model(key):
                        self.model_status.configure(text='The 3D viewport could not open.')
            except ValueError as exc:
                if isinstance(key,tuple):
                    if key==self.current_selection():
                        self.model_status.configure(text='3D model unavailable. Select the suit again to retry.')
                else:
                    self.status.set(str(exc))
            finally:
                self.requests.remove(key)
                if self.catalog:
                    self.refresh_save()
        if self.requests:
            self.desktop.root.after(80, self.tick)


class DirectGame(CommunityGame):
    """Own one native process at a time while retaining the public seat between rounds."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.public_name = None
        self.round_change = None
        self.retiring_public_session = None

    def start_public(self, name, *, cancel=None):
        self.public_name = name
        try:
            status = self._start(public_name=name, public_cancel=cancel)
        except Exception:
            if self.role == 'public' and self.status in ('failed', 'stopped'):
                self.release_public()
            raise
        if status == 'stopped':
            self.release_public()
        return status

    def continue_public(self, next_round):
        with self.lock:
            current = self.public_round
            if (self.role != 'public' or self.status not in ('starting', 'playing') or self.thread is None
                    or self.round_change is not None or current is None
                    or current[0] != next_round[0] or current[1] >= next_round[1]):
                return None
            cancel = self.round_change = threading.Event()
            self.retiring_public_session = self.current_artifacts
            old_thread = self.thread
        try:
            super().stop()
            old_thread.join(45)
            with self.lock:
                if old_thread.is_alive() or self.status == 'quarantined':
                    raise CommunityError('The previous round is still closing. Wait for it to close before rejoining.')
                self.retiring_public_session = None
            return self.start_public(self.public_name, cancel=cancel)
        finally:
            with self.lock:
                self.retiring_public_session = None
                self.round_change = None

    def stop(self):
        with self.lock:
            if self.round_change is not None:
                self.round_change.set()
            super().stop()

    def release_public(self):
        try:
            self.lobby.public_leave()
        except CommunityError:
            pass  # The host expires seats that never reconnect.

    def _run(self, argv, artifacts):
        def ready_run():
            with self.lock:
                return self.run if self.status == 'playing' else None

        if self.role == 'player':
            with self.lobby.proximity_game(ready_run):
                super()._run(argv, artifacts)
        elif self.role == 'public':
            try:
                super()._run(argv, artifacts)
            finally:
                with self.lock:
                    retain_seat = artifacts == self.retiring_public_session or self.status == 'quarantined'
                if not retain_seat:
                    self.release_public()
        else:
            super()._run(argv, artifacts)


class PublicCTFPanel:
    def __init__(self, tk, desktop, lobby):
        from desktop_launcher import BG, MUTED, match_result_for
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
        self.result_button = desktop.button(actions, 'Match results',
                                            lambda: desktop.show_match_result(match_result_for(self.state)), False)
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

    def center_ballot(self, ballot):
        bounds = (0, 0, ballot.winfo_screenwidth(), ballot.winfo_screenheight())
        run = getattr(self.desktop.game, 'run', None)
        if os.name == 'nt' and run is not None:
            try:
                focus = OwnedGameFocus(run)
                try:
                    bounds = focus.foreground_bounds() or bounds
                finally:
                    focus.close()
            except (OSError, ValueError, KeyError):
                pass  # The game can close while the ballot is being opened.
        ballot.update_idletasks()
        left, top, right, bottom = bounds
        x = left + max(0, (right - left - ballot.winfo_reqwidth()) // 2)
        y = top + max(0, (bottom - top - ballot.winfo_reqheight()) // 2)
        ballot.geometry(f'+{x}+{y}')
        ballot.deiconify()
        ballot.lift()

    def refresh_ballot(self, state, active):
        from desktop_launcher import ACCENT, BG, MUTED, PANEL, TEXT

        if state.get('phase') != 'voting' or not state.get('team') or not active:
            if self.ballot is not None:
                self.ballot.destroy()
                self.ballot = None
            self.ballot_key = None
            return
        round_id = state['round']
        key = (round_id, state['seconds'], state['selected'],
               tuple((option['id'], option['votes']) for option in state['options']))
        opening = self.ballot is None
        if opening:
            self.ballot = self.tk.Toplevel(self.root)
            self.ballot.withdraw()
            self.ballot.title('Vote for the next map')
            self.ballot.attributes('-topmost', True)
            self.ballot.resizable(False, False)
            self.ballot.protocol('WM_DELETE_WINDOW', self.ballot.withdraw)
            self.ballot.configure(bg=BG)
            self.ballot_message = self.tk.StringVar()
            self.tk.Label(self.ballot, text='Vote for the next map', font=('Segoe UI', 24, 'bold'),
                          bg=BG, fg=TEXT).pack(padx=32, pady=(24, 4))
            self.tk.Label(self.ballot, textvariable=self.ballot_message, font=('Segoe UI', 15),
                          bg=BG, fg=MUTED).pack(padx=32, pady=(0, 20))
            self.ballot_buttons = {}
            for option in state['options']:
                map_id = option['id']
                button = self.tk.Button(self.ballot, width=30, pady=12, font=('Segoe UI', 18, 'bold'),
                    bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=BG, relief='flat',
                    command=lambda choice=map_id: self.submit('vote', lambda: self.lobby.public_vote(round_id, choice)))
                button.pack(fill='x', padx=32, pady=(0, 12))
                self.ballot_buttons[map_id] = button
        if self.ballot_key != key:
            self.ballot_key = key
            self.ballot_message.set(f'{state["seconds"]} seconds left')
            for option in state['options']:
                selected = state['selected'] == option['id']
                prefix = '✓ ' if selected else ''
                self.ballot_buttons[option['id']].configure(text=f'{prefix}{option["label"]} ({option["votes"]})',
                    bg=ACCENT if selected else PANEL, fg=BG if selected else TEXT)
        if opening:
            self.center_ballot(self.ballot)

    def tick(self):
        from desktop_launcher import match_result_for

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
                    if match_result_for(state):
                        self.result_button.pack(side='left', padx=(8, 0))
                    else:
                        self.result_button.pack_forget()
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
        if public and state.get('phase') == 'playing' and state.get('team'):
            current = game.public_round
            round_id = state.get('round')
            if current and current[0] == state.get('id') and type(round_id) is int and round_id > current[1]:
                self.submit('continue', lambda: game.continue_public((current[0], round_id)))
        if public and ui.game_status != 'playing':
            self.status.set(ui.status.get())
        continuing = 'continue' in self.pending
        can_join = state.get('phase') == 'playing' and not active and not continuing and 'start' not in self.pending
        self.join.configure(state='normal' if can_join else 'disabled')
        self.leave.configure(state='normal' if public or continuing else 'disabled')
        self.refresh_ballot(state, public and ui.game_status == 'playing')
        now = time.monotonic()
        if now >= self.poll_at and (public or ui.current_panel == 'public'):
            self.poll_at = now + 2
            self.submit('poll', lambda: self.lobby.public_state(renew=public))
        self.root.after(150, self.tick)

RANKED_TOTALS = (
    ('kills', 'Kills', 51, ('kills', 'kill')),
    ('deaths', 'Deaths', 62, ('deaths', 'death')),
    ('assists', 'Assists', 63, ('assists', 'assist', 'killassists')),
    ('captures', 'Captures', 75, ('captures', 'capture', 'flagcaptures', 'flagcapture', 'flagcaps')),
    ('returns', 'Returns', 68, ('returns', 'return', 'flagreturns', 'flagreturn')),
    ('grabs', 'Grabs', 57, ('flaggrabs',)),
    ('held', 'Flag time', 75, ('flagheldseconds',)),
)
RANKED_SUMMARY_KEYS = {key for _, _, _, keys in RANKED_TOTALS for key in keys}


def ranked_stat_key(key):
    name = key.rsplit('.', 1)[-1].lower().removeprefix('stat_')
    return re.sub(r'[^a-z0-9]', '', name)


class RankedPugPanel:
    """Launcher views for the current ranked room and its published statistics."""

    def __init__(self, tk, desktop, lobby):
        from tkinter import ttk
        from desktop_launcher import BG, MUTED, PANEL

        self.ui, self.lobby = desktop, lobby
        self.state, self.ranked_rows = {}, {}
        self.responses = queue.Queue()
        self.pending = set()
        self.poll_at = 0
        self.offset = 0
        self.board_query = ''
        self.board_sort = 'mu'
        self.queue_revision = 0
        self.panel = panel = tk.Frame(desktop.root, bg=BG)
        self.stats_panel = stats = tk.Frame(desktop.root, bg=BG)
        desktop.button(desktop.play_actions, 'Ranked PUG 7v7', lambda: desktop.show_panel('pug'), False).pack(
            side='left', padx=(6, 0))
        desktop.button(desktop.sidebar, 'Stats', lambda: desktop.show_panel('stats'), False).pack(
            fill='x', padx=18, pady=(6, 0))

        desktop.label(panel, 'Ranked PUG', 26, True).pack(anchor='w')
        self.status = tk.StringVar()
        status = desktop.label(panel, '', 11, color=MUTED)
        status.configure(textvariable=self.status, justify='left', wraplength=550)
        status.pack(anchor='w', pady=(5, 12))
        controls = tk.Frame(panel, bg=BG)
        controls.pack(fill='x', pady=(0, 12))
        self.join = desktop.button(controls, 'Join 7v7 queue', self.join_queue)
        self.leave = desktop.button(controls, 'Leave queue', lambda: self.action('leave'), False)
        self.launch = desktop.button(controls, 'Launch game', self.launch_game)
        for button in (self.join, self.leave, self.launch):
            button.pack(side='left', padx=(0, 8))

        self.ballot = tk.Frame(panel, bg=BG)
        self.ballot.pack(fill='x', pady=(0, 14))
        self.votes = []
        for col in range(3):
            self.ballot.columnconfigure(col, weight=1, uniform='ballot')
            button = desktop.button(self.ballot, '', lambda index=col: self.vote(index), False)
            button.configure(anchor='center', justify='center', wraplength=155)
            button.grid(row=0, column=col, sticky='nsew', padx=(0, 7))
            self.votes.append(button)
        self.roster = tk.Frame(panel, bg=PANEL, padx=12, pady=10)
        self.roster.pack(fill='both', expand=True)
        self.teams = {}
        for column, (side, label, color) in enumerate((('blue', 'Blue team', '#80c8ff'),
                                                       ('red', 'Red team', '#ff9a9a'))):
            self.roster.columnconfigure(column, weight=1, uniform='teams')
            card = tk.Frame(self.roster, bg=PANEL)
            card.grid(row=0, column=column, sticky='nsew')
            desktop.label(card, label, 12, True, color=color, bg=PANEL).pack(anchor='w')
            names = desktop.label(card, '', 10, bg=PANEL)
            names.configure(justify='left', anchor='nw')
            names.pack(fill='both', expand=True, pady=(5, 0))
            self.teams[side] = names

        desktop.label(stats, 'Ranked stats', 26, True).pack(anchor='w')
        search = tk.Frame(stats, bg=BG)
        search.pack(fill='x', pady=(10, 8))
        self.query = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.query, width=22)
        entry.pack(side='left')
        entry.bind('<Return>', lambda _event: self.filter_board())
        desktop.button(search, 'Search players', self.filter_board, False).pack(side='left', padx=6)
        desktop.button(search, 'My stats', lambda: self.load_stats(profile=None), False).pack(side='left')
        self.back = desktop.button(search, 'Previous', lambda: self.page(-25), False)
        self.next = desktop.button(search, 'Next', lambda: self.page(25), False)
        self.next.pack(side='right')
        self.back.pack(side='right', padx=6)
        headings = (('rank', 'Rank', 50), ('name', 'Player', 145), ('mu', 'μ', 56),
                    ('record', 'W–L–D', 80)) + tuple((key, title, width) for key, title, width, _ in RANKED_TOTALS)
        board = tk.Frame(stats, bg=BG)
        board.pack(fill='both', expand=True)
        self.table = ttk.Treeview(board, columns=[item[0] for item in headings],
                                  show='headings', style='Live.Treeview', selectmode='browse', height=8)
        scroll = ttk.Scrollbar(board, orient='vertical', command=self.table.yview)
        horizontal = ttk.Scrollbar(board, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        board.rowconfigure(0, weight=1)
        board.columnconfigure(0, weight=1)
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        sorts = {'rank': 'mu', 'mu': 'mu', 'record': 'wins', 'grabs': 'flagGrabs', 'held': 'flagHeldSeconds'}
        for key, title, width in headings:
            self.table.heading(key, text=title)
            if key in sorts:
                self.table.heading(key, command=lambda sort=sorts[key]: self.sort_board(sort))
            self.table.column(key, width=width, minwidth=width, stretch=key == 'name',
                              anchor='w' if key == 'name' else 'center')
        self.table.bind('<<TreeviewSelect>>', self.select_ranked_player)
        self.profile = tk.StringVar()
        ttk.Label(stats, textvariable=self.profile, wraplength=575, justify='left').pack(
            anchor='w', fill='x', pady=(8, 0))
        profile_box = tk.Frame(stats, bg=BG)
        profile_box.pack(fill='both', pady=(4, 0))
        self.detail = ttk.Treeview(profile_box, columns=('stat', 'total'), show='headings',
                                   style='Live.Treeview', height=len(RANKED_TOTALS))
        self.detail.heading('stat', text='Statistic')
        self.detail.heading('total', text='Career total')
        detail_scroll = ttk.Scrollbar(profile_box, orient='vertical', command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(side='left', fill='both', expand=True)
        detail_scroll.pack(side='right', fill='y')
        self.render()
        desktop.root.after(150, self.tick)

    def submit(self, kind, work):
        if kind in self.pending:
            return
        self.pending.add(kind)

        def request():
            try:
                self.responses.put((kind, work(), None))
            except (CommunityError, OSError, ValueError, KeyError, TypeError) as exc:
                self.responses.put((kind, None, str(exc)))

        threading.Thread(target=request, name='ranked-' + kind, daemon=True).start()

    def action(self, action, **data):
        if 'queue' not in self.pending:
            self.queue_revision += 1
            self.submit('queue', lambda: self.lobby.pug(action, **data))
            self.render()

    def poll(self):
        revision = self.queue_revision
        if 'queue' not in self.pending:
            self.submit('poll', lambda: (revision, self.lobby.pug('state')))

    def open(self, page):
        if page == 'pug':
            self.poll()
        else:
            self.load_stats()

    def show_page(self, name):
        self.panel.pack_forget()
        self.stats_panel.pack_forget()
        if name not in ('pug', 'stats'):
            return False
        self.ui.current_panel = name
        self.ui.lobby_panel.pack_forget()
        self.ui.live_panel.pack_forget()
        panel = self.panel if name == 'pug' else self.stats_panel
        panel.pack(side='left', fill='both', expand=True, padx=32, pady=24)
        self.open(name)
        return True

    def join_queue(self):
        try:
            name = self.ui.player_name_for_action()
        except (ValueError, RuntimeError) as exc:
            self.status.set(str(exc))
            return
        self.action('join', name=name)

    def vote(self, index):
        room = self.state.get('room')
        if room and room['phase'] == 'voting':
            self.action('vote', room=room['id'], map=room['options'][index]['id'])

    def launch_game(self):
        room = self.state.get('room')
        if room and room.get('game') and self.idle_game():
            if self.ui.game is None:
                self.ui.game = self.ui.game_factory(self.lobby)
            game = self.ui.game
            self.submit('launch', lambda: game.start_pug(room['id'], room['game']))
            self.render()

    def idle_game(self):
        return (self.ui.game_status in ('idle', 'stopped', 'finished', 'failed')
                and not self.ui.controls_busy and 'launch' not in self.pending)

    def render(self):
        state = self.state
        room = state.get('room')
        queued = state.get('queued') is True
        idle = self.idle_game()
        busy = 'queue' in self.pending
        self.join.configure(state='normal' if idle and not (room or queued or busy) else 'disabled')
        self.leave.configure(text='Withdraw from match' if room else 'Leave queue',
                             state='normal' if not busy and
                             (queued or (room and room['phase'] != 'playing' and idle)) else 'disabled')
        self.launch.configure(state='normal' if idle and room and room.get('game') else 'disabled')
        if room:
            phase = room['phase']
            self.roster.pack(fill='both', expand=True)
            for side, label in self.teams.items():
                label.configure(text='\n'.join(room[side]))
            if phase == 'voting':
                self.ballot.pack(fill='x', pady=(0, 14), before=self.roster)
                for button, choice in zip(self.votes, room['options']):
                    picked = ' ✓' if room.get('myVote') == choice['id'] else ''
                    button.configure(text=f"{choice['label']}{picked}\n{choice['votes']} votes",
                                     state='normal' if not busy else 'disabled')
                message = f"Vote for a map · {room['seconds']}s left · You’re on {room['team'].title()}"
            else:
                self.ballot.pack_forget()
                label = self.lobby.map_label(room['map']) or room['map']
                message = f"{label} · You’re on {room['team'].title()}"
                if room.get('progress'):
                    message += '\n' + room['progress']
                elif phase == 'allocating':
                    message += '\nWaiting for a game slot.'
                else:
                    message += '\nPreparing the game server.'
        else:
            self.ballot.pack_forget()
            self.roster.pack_forget()
            message = f"{state.get('queuedPlayers', 0)}/14 queued · Random teams · Three-map vote"
            if state.get('notice'):
                message += '\n' + state['notice']
        if 'launch' in self.pending:
            message += '\nPreparing your game…'
        self.status.set(message)

    def filter_board(self):
        self.offset, self.board_query = 0, self.query.get().strip()
        self.load_stats()

    def page(self, change):
        if 'stats' not in self.pending:
            self.offset = max(0, self.offset + change)
            self.load_stats()

    def sort_board(self, sort):
        if 'stats' not in self.pending:
            self.offset, self.board_sort = 0, sort
            self.load_stats()

    def load_stats(self, profile=None):
        data = dict(query=self.board_query, offset=self.offset, sort=self.board_sort)
        if profile is not None:
            data['profile'] = profile
        self.submit('stats', lambda: self.lobby.pug('stats', **data))

    @staticmethod
    def duration(seconds):
        minutes, rest = divmod(int(seconds), 60)
        return f'{minutes}:{rest:02d}'

    @classmethod
    def summary(cls, stats):
        by_name = {}
        for key, value in stats.items():
            by_name.setdefault(ranked_stat_key(key), value)
        totals = []
        for column, label, _, keys in RANKED_TOTALS:
            value = stats.get(f'native.{label}')
            if value is None:
                value = next((by_name[key] for key in keys if key in by_name), 0)
            totals.append((label, cls.duration(value) if column == 'held' else f'{value:,.0f}'))
        return totals

    def render_stats(self, result):
        self.table.delete(*self.table.get_children())
        self.ranked_rows = {str(row['id']): row for row in result['players']}
        for identity, row in self.ranked_rows.items():
            self.table.insert('', 'end', iid=identity, values=(
                row['rank'], row['name'], f"{row['mu']:.2f}", f"{row['wins']}–{row['losses']}–{row['draws']}",
                *(value for _, value in self.summary(row['stats']))))
        self.back.configure(state='normal' if self.offset else 'disabled')
        self.next.configure(state='normal' if result['hasMore'] else 'disabled')
        self.render_profile(result['profile'])

    def select_ranked_player(self, _event):
        selected = self.table.selection()
        if selected:
            self.render_profile(self.ranked_rows.get(selected[0]))

    def render_profile(self, row):
        self.detail.delete(*self.detail.get_children())
        if row is None:
            self.profile.set('No completed ranked matches for this player yet. Starting μ is 25.')
            return
        self.profile.set(f"#{row['rank']}  {row['name']}   ·   μ {row['mu']:.2f}   ·   σ {row['sigma']:.2f}")
        for label, total in self.summary(row['stats']):
            self.detail.insert('', 'end', values=(label, total))
        for key, value in sorted(row['stats'].items()):
            if ranked_stat_key(key) in RANKED_SUMMARY_KEYS:
                continue
            label = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', key.removeprefix('native.').split('.')[-1])
            label, total = label[:1].upper() + label[1:], f'{value:,.3f}'.rstrip('0').rstrip('.') if value % 1 else f'{int(value):,}'
            self.detail.insert('', 'end', values=(label, total))

    def tick(self):
        if self.ui.closing:
            return
        try:
            while True:
                kind, value, error = self.responses.get_nowait()
                self.pending.remove(kind)
                if kind == 'stats':
                    if error:
                        self.profile.set(error)
                    else:
                        self.render_stats(value)
                else:
                    if kind == 'queue' and error is None:
                        self.state = value
                    if kind == 'poll' and error is None:
                        revision, view = value
                        if revision != self.queue_revision:
                            continue
                        self.state = view
                    self.render()
                    if error:
                        self.status.set(error)
        except queue.Empty:
            pass
        self.launch.configure(state='normal' if self.idle_game() and
                              (self.state.get('room') or {}).get('game') else 'disabled')
        now = time.monotonic()
        if now >= self.poll_at and (self.ui.current_panel == 'pug'
                                    or self.state.get('queued') or self.state.get('room')):
            self.poll_at = now + 2
            self.poll()
        self.ui.root.after(150, self.tick)

class LauncherTips:
    """Present optional host messages without blocking the launcher event loop."""

    def __init__(self, tk, desktop, lobby, local, frame):
        from datetime import datetime, timezone
        from desktop_launcher import MUTED

        self.tk, self.desktop, self.lobby, self.frame = tk, desktop, lobby, frame
        self.clock = lambda: datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.messages = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        self.document = {'version': 1, 'admin_messages': [], 'tips': []}
        self.render_key = None
        self.local_events = set()
        scope = hashlib.sha256(lobby.authority.encode()).hexdigest()[:24]
        self.path = local / ('tool-tips-seen-' + scope + '.json')
        try:
            stored = read_json(self.path, TOOL_TIPS_LIMIT)
            self.seen = dict.fromkeys(k for k in stored[-200:] if isinstance(k, str)) if isinstance(stored, list) else {}
        except (OSError, ValueError):
            self.seen = {}
        self.bg = frame.cget('bg')
        self.admin_region, self.admin = self.region()
        self.admin_region.pack(fill='x')
        self.tip_region, self.body = self.region()
        self.muted = MUTED
        threading.Thread(target=self.fetch, name='launcher-tool-tips', daemon=True).start()
        self.tick()

    def region(self):
        window = self.tk.Frame(self.frame, bg=self.bg)
        canvas = self.tk.Canvas(window, bg=self.bg, height=1, highlightthickness=0,
                                borderwidth=0)
        scrollbar = self.tk.Scrollbar(window, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='x', expand=True)
        content = self.tk.Frame(canvas, bg=self.bg)
        item = canvas.create_window(0, 0, window=content, anchor='nw')

        def resize(_event):
            height = content.winfo_reqheight()
            if height > 92:
                if not scrollbar.winfo_manager():
                    scrollbar.pack(side='right', fill='y')
            else:
                scrollbar.pack_forget()
                canvas.yview_moveto(0)
            if canvas.cget('height') != min(height, 92):
                canvas.configure(height=min(height, 92))
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), height))

        content.bind('<Configure>', resize)
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        return window, content

    def fetch(self):
        while not self.closed.is_set():
            try:
                document = decode_tool_tips(self.lobby._request(TOOL_TIPS_ROUTE.removeprefix('/api/')))
            except (CommunityError, ValueError, OSError):
                document = {'version': 1, 'admin_messages': [], 'tips': []}
            try:
                self.messages.put_nowait(document)
            except queue.Full:
                pass
            self.closed.wait(30)

    def acknowledge(self, key):
        if key in self.seen:
            return
        self.seen[key] = None
        while len(self.seen) > 200:
            del self.seen[next(iter(self.seen))]
        try:
            write_json(self.path, list(self.seen))
        except OSError:
            pass

    def event(self, kind, target):
        if kind == 'open_tab' and target == 'settings':
            self.acknowledge('builtin-voice-settings')
        self.local_events.add((kind, target))
        for row in self.document['tips']:
            if row.get('ack') == kind and row.get('ack_target') == target:
                self.acknowledge(row['id'])

    def populate(self, frame, rows):
        for child in frame.winfo_children():
            child.destroy()
        for row in rows:
            color = row.get('color', self.muted)
            props = dict(text=row['text'], bg=self.bg, fg=color, justify='left',
                         anchor='w', wraplength=155, font=('Segoe UI', 9))
            if row.get('ack') == 'click':
                widget = self.tk.Button(frame, relief='flat', bd=0, cursor='hand2',
                                        padx=0, pady=0, activebackground=self.bg,
                                        activeforeground=color, command=lambda key=row['id']: self.acknowledge(key),
                                        **props)
            else:
                widget = self.tk.Label(frame, padx=0, pady=0, **props)
            widget.pack(fill='x', pady=(3, 1))

    def tick(self):
        if self.desktop.closing:
            self.closed.set()
            return
        try:
            self.document = self.messages.get_nowait()
        except queue.Empty:
            pass
        panel = {'lobbies': 'create_lobby', 'live': 'lobby_browser', 'public': 'public_ctf'}.get(
            self.desktop.current_panel, self.desktop.current_panel)
        settings = self.desktop.settings_window
        if settings is not None and settings.winfo_exists():
            panel = 'settings'
        self.event('open_tab', panel)
        for row in self.document['tips']:
            if row.get('ack') in ('open_tab', 'setting_changed') and (row['ack'], row['ack_target']) in self.local_events:
                self.acknowledge(row['id'])
        now = self.clock()

        def visible(row):
            return (row['id'] not in self.seen and (not row.get('starts') or row['starts'] <= now)
                    and (not row.get('expires') or now < row['expires']))

        admin = [row for row in self.document['admin_messages'] if visible(row)]
        tips = [row for row in self.document['tips'] if row.get('tab', 'all') in ('all', panel) and visible(row)]
        known = {row['id'] for row in self.document['tips']}
        if (self.lobby.proximity_supported and 'prox-voice-settings' not in known
                and 'builtin-voice-settings' not in self.seen):
            if panel == 'settings':
                self.acknowledge('builtin-voice-settings')
            else:
                tips.append({'id': 'builtin-voice-settings', 'text': 'Proximity voice controls are in Settings.',
                             'sticky': True, 'priority': 100})
        tips.sort(key=lambda row: (not row.get('sticky', False), row.get('tab', 'all') != 'all',
                                   -row.get('priority', 0)))
        key = (admin, tips)
        if key != self.render_key:
            self.render_key = key
            self.populate(self.admin, admin)
            self.populate(self.body, tips)
        self.desktop.root.after(600, self.tick)


class OfflineLobby(CommunityClient):
    """Keep the normal Starter window available for Local Play when offline."""

    public_supported = armor_supported = proximity_supported = public_only = False

    @staticmethod
    def accepts_server_address(address):
        return str(address) == '127.0.0.1'

    def __init__(self):
        super().__init__('localhost', 443, '127.0.0.1', DIRECT_BRIDGE_POLICY)

    def _request(self, *_args, **_kwargs):
        raise CommunityConnectionError('The remote host is unavailable. Local Play is available on this PC.')

    def close(self):
        pass


def main(root=ROOT, *, on_ready=None):
    import tkinter as tk
    from tkinter import filedialog,messagebox
    from desktop_launcher import Desktop
    from startup_paths import installation_options
    from client_support import discover_game
    from map_sync import MapSync
    from steam_identity import read_steam_name
    local=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'Tribes3DirectStarter'
    local.mkdir(parents=True,exist_ok=True);saved=local/'connection.json'
    chooser=tk.Tk();chooser.withdraw()
    lobby=None
    local_available=False
    try:
        try:
            game,workspace=installation_options();source=discover_game(game)
            local_available = LocalHostSession(root, source, workspace).available
        except RuntimeError as exc:
            # Steam discovery reports a missing or ambiguous game as RuntimeError.
            raise ValueError(str(exc)) from exc
        if (root/GROUP_FILE).exists():
            connection=group_connection(root,local)
        else:
            if not saved.exists() and not local_available:
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
                if not local_available:
                    messagebox.showerror('Direct host connection','Could not open the lobby. Ask the host to check your access, certificate and TCP forwarding.')
    except (OSError, ValueError, CommunityError) as exc:
        if lobby is not None:
            lobby.close()
        lobby=None
        if not local_available:
            messagebox.showerror('Direct Starter setup',str(exc))
    finally:chooser.destroy()
    if lobby is None and local_available:
        lobby = OfflineLobby()
    if lobby is None:
        # A canceled invitation or unreachable host does not invalidate the update.
        if on_ready is not None:
            on_ready()
        return
    class DirectDesktop(Desktop):
        public_panel = None
        armor_panel = None
        local_host = None
        local_desktop = None
        local_room = None
        local_row = 'this-pc-local-host'

        def local_play_enabled(self):
            return (not self.closing and not self.controls_busy and self.room is None
                    and self.game_status in ('idle', 'stopped', 'finished', 'failed'))

        def refresh_local_controls(self):
            buttons = getattr(self, 'local_buttons', ())
            if not buttons:
                return
            server = self.local_host
            running = server is not None and server.thread is not None and server.thread.is_alive()
            if server is not None and not running and not self.controls_busy:
                self.local_host = self.local_room = None
            enabled = (running or self.local_play_enabled()) and not self.controls_busy
            for button in buttons:
                button.configure(text='Stop local host' if running else 'Start local host',
                                 state='normal' if enabled else 'disabled')
            if self.current_panel == 'live':
                self.render_local_row()

        def render_local_row(self):
            server = self.local_host
            if server is None or server.client is None or not server.thread.is_alive():
                if self.live_list.exists(self.local_row):
                    self.live_list.delete(self.local_row)
                return
            room = self.local_room or {}
            map_name = server.client.map_label(room['map']) if room.get('map') else 'Choose in lobby'
            players = str(len(room.get('players', [])))
            values = ('Local host · This PC', map_name or room.get('map', ''), players, '—', 'Private')
            if self.live_list.exists(self.local_row):
                self.live_list.item(self.local_row, values=values)
            else:
                self.live_list.insert('', 0, iid=self.local_row, values=values)

        def render_live_matches(self, matches):
            local_selected = self.live_list.selection() == (self.local_row,)
            super().render_live_matches(matches)
            self.render_local_row()
            if local_selected and self.live_list.exists(self.local_row):
                self.live_list.selection_set(self.local_row)
            self.render_live_controls()

        def render_live_controls(self):
            super().render_live_controls()
            self.refresh_local_controls()
            if self.live_list.exists(self.local_row) and not self.live_targets and self.watch_id is None:
                self.live_status.set('The private host on this PC is available.')
            if self.live_list.selection() == (self.local_row,):
                if not self.live_join_row.winfo_manager():
                    self.live_join_row.pack(before=self.live_status_label, fill='x', pady=(8, 0))
                self.live_team.configure(state='disabled')
                self.live_join_reason.set('Opens the private lobby on this PC.')
                self.live_join_button.configure(text='Open local host',
                                                state='normal' if self.local_play_enabled() else 'disabled')

        def join_live_selected(self):
            if self.live_list.selection() == (self.local_row,):
                if self.local_play_enabled():
                    self.open_local_host()
                return
            super().join_live_selected()

        def toggle_local_host(self):
            previous = self.local_host
            if previous is not None:
                self.stop_local_host(previous)
                return
            if not self.local_play_enabled():
                return
            server = LocalHostSession(root, source, workspace)
            self.local_host = server
            self.status.set('Verifying the local host package…')

            def started(_):
                self.status.set('Local host ready. Choose it in Lobby Browser.')
                self.show_panel('live')
                self.render_local_row()
                if self.live_list.exists(self.local_row):
                    self.live_list.selection_set(self.local_row)
                self.render_live_controls()

            self.run_async(server.start, started)
            self.refresh_local_controls()

        def stop_local_host(self, server):
            self.status.set('Stopping the local host…')

            def stopped(_):
                if self.local_host is server:
                    self.local_host = self.local_room = None
                    self.status.set('Local host stopped.')
                self.render_live_controls()

            self.run_async(server.stop, stopped)

        def open_local_host(self):
            server = self.local_host
            if server is None or server.client is None or not server.thread.is_alive():
                self.status.set('The local host has stopped.')
                self.render_live_controls()
                return
            client = server.client
            window = tk.Toplevel(self.root)
            local_workspace = workspace/'local-play-client'
            local_sync = MapSync(client, root, local_workspace)
            owner = self

            class LocalDesktop(Desktop):
                def render(self, room):
                    owner.local_room = room
                    super().render(room)

                def close(self):
                    match = (self.room or {}).get('match')
                    super().close()
                    if not isinstance(match, dict) or match.get('status') not in ('starting', 'ready'):
                        owner.local_room = None
                    owner.local_desktop = None
                    owner.root.deiconify()
                    owner.render_live_controls()

            factory = lambda current: DirectGame(current, root, source, local_workspace,
                                                 local_workspace/'direct-desktop-control', map_sync=local_sync)
            self.local_desktop = LocalDesktop(window, client, factory, map_sync=local_sync)
            if self.name.get().strip():
                self.local_desktop.name.set(self.name.get())
            window.title('Tribes Rivals: Clan Wars · Local Play')

            def stop_here():
                if self.local_desktop is not None:
                    self.local_desktop.close()
                self.stop_local_host(server)

            self.local_desktop.button(self.local_desktop.play_actions, 'Stop local host', stop_here, False).pack(
                side='left', padx=(4, 0))
            self.root.withdraw()
            self.watch_local_host(server, self.local_desktop)

        def watch_local_host(self, server, desktop):
            if self.closing or self.local_desktop is not desktop:
                return
            if not server.thread.is_alive():
                desktop.close()
                self.status.set('The local host stopped. The local match was closed.')
                return
            self.root.after(500, self.watch_local_host, server, desktop)
        pug_panel = None

        def show_panel(self, name):
            if self.closing:
                return
            if hasattr(self, 'tool_tips'):
                tab = {'lobbies': 'create_lobby', 'live': 'lobby_browser', 'public': 'public_ctf'}.get(name, name)
                self.tool_tips.event('open_tab', tab)
            if self.armor_panel is not None:
                self.armor_panel.panel.pack_forget()
            if self.public_panel is not None:
                self.public_panel.panel.pack_forget()
            if self.maps_panel is not None:
                self.maps_panel.pack_forget()
            if self.pug_panel is not None:
                self.pug_panel.panel.pack_forget()
                self.pug_panel.stats_panel.pack_forget()
                if name in ('pug', 'stats'):
                    self.current_panel = name
                    self.lobby_panel.pack_forget()
                    self.live_panel.pack_forget()
                    panel = self.pug_panel.panel if name == 'pug' else self.pug_panel.stats_panel
                    panel.pack(side='left', fill='both', expand=True, padx=32, pady=24)
                    self.pug_panel.open(name)
                    return
            if name == 'armor' and self.armor_panel is not None:
                self.current_panel = 'armor'
                self.lobby_panel.pack_forget()
                self.live_panel.pack_forget()
                self.armor_panel.panel.pack(side='left', fill='both', expand=True, padx=32, pady=28)
                self.armor_panel.open()
                return
            if self.public_panel is not None:
                if name == 'public' or (lobby.public_only and name != 'maps'):
                    self.current_panel = 'public'
                    self.lobby_panel.pack_forget()
                    self.live_panel.pack_forget()
                    self.public_panel.panel.pack(side='left', fill='both', expand=True, padx=32, pady=28)
                    return
            super().show_panel(name)

        def refresh_voice_notice(self):
            enabled = lobby.proximity_enabled.is_set()
            self.voice_notice.configure(text='On' if enabled else 'Off',
                                        fg='#80e6bd' if enabled else '#ffaaaa')

        def show_settings(self):
            if hasattr(self, 'tool_tips'):
                self.tool_tips.event('open_tab', 'settings')
            previous = self.settings_window
            super().show_settings()
            window = self.settings_window
            if window is previous or not lobby.proximity_supported:
                return
            from desktop_launcher import BG, MUTED, TEXT
            self.label(window, 'Proximity voice', 16, True).pack(anchor='w', pady=(14, 4))
            row = tk.Frame(window, bg=BG)
            row.pack(anchor='w')
            enabled = tk.BooleanVar(window, value=lobby.proximity_enabled.is_set())
            key = tk.StringVar(window, value=f'Change key ({PTT_KEY_NAMES[lobby.proximity_key]})')

            def toggle():
                lobby.set_proximity_voice(enabled.get())
                self.refresh_voice_notice()
                if hasattr(self, 'tool_tips'):
                    self.tool_tips.event('setting_changed', 'proximity_voice')

            def save_key(value):
                lobby.bind_proximity_key(value)
                key.set(f'Change key ({PTT_KEY_NAMES[lobby.proximity_key]})')

            tk.Checkbutton(row, text='Enable proximity voice', variable=enabled, command=toggle,
                           bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT,
                           selectcolor='#20374a').pack(side='left')
            button = self.button(row, 'Change key', lambda: choose_proximity_key(window, save_key), False)
            button.configure(textvariable=key)
            button.pack(side='left', padx=(12, 0))
            detail = tk.Label(window, bg=BG, fg=MUTED, anchor='w')
            detail.pack(anchor='w', pady=(6, 0))

            pending = None

            def refresh_detail():
                nonlocal pending
                detail.configure(text=lobby.proximity_status)
                pending = detail.after(250, refresh_detail)

            detail.bind('<Destroy>', lambda _event: detail.after_cancel(pending) if pending else None)
            refresh_detail()

        def close(self):
            if hasattr(self, 'tool_tips'):
                self.tool_tips.closed.set()
            if self.local_desktop is not None:
                self.local_desktop.close()
            try:super().close()
            finally:lobby.close()

    try:
        window=tk.Tk();window.title('TRIBES 3 — Direct Host Starter')
        map_sync=MapSync(lobby,root,workspace)
        factory=lambda current:DirectGame(current,root,source,workspace,workspace/'direct-desktop-control',map_sync=map_sync)
        gui=DirectDesktop(window,lobby,factory,
                          steam_name_loader=lambda:read_steam_name(source,root/'base-game-manifest.json'),
                          map_sync=map_sync)
        if local_available:
            gui.local_buttons = [
                gui.button(parent, 'Start local host', gui.toggle_local_host, False)
                for parent in (gui.play_actions, gui.live_refresh_button.master)
            ]
            for button in gui.local_buttons:
                button.pack(side='left', padx=(6, 0))
            gui.refresh_local_controls()
        if lobby.public_supported:
            gui.public_panel = PublicCTFPanel(tk, gui, lobby)
            gui.show_panel('public' if lobby.public_only else 'lobbies')
        if lobby.pug_supported:
            gui.pug_panel = RankedPugPanel(tk, gui, lobby)
        if lobby.armor_supported:
            gui.armor_panel = ArmorPanel(tk, gui, lobby, model_directory=root/'armor-models')
        if gui.settings_nav is not None:
            gui.settings_nav.pack_forget()
            gui.settings_nav.pack(fill='x', padx=18, pady=(6, 0))
        sidebar_bg = '#0d1927'
        tips = tk.Frame(gui.sidebar, bg=sidebar_bg)
        tips.pack(fill='x', padx=20, pady=(16, 0))
        gui.label(tips, 'Tool Tips', 10, True, bg=sidebar_bg).pack(anchor='w')
        gui.tool_tips = LauncherTips(tk, gui, lobby, local, tips)
        if lobby.proximity_supported:
            voice = tk.Frame(tips, bg=sidebar_bg)
            voice.pack(anchor='w', pady=(5, 0))
            gui.label(voice, 'Proximity voice', 9, bg=sidebar_bg).pack(side='left')
            gui.voice_notice = gui.label(voice, '', 9, True, bg=sidebar_bg)
            gui.voice_notice.pack(side='left', padx=(5, 0))
            gui.refresh_voice_notice()
        gui.tool_tips.tip_region.pack(fill='x')
        if gui.settings_nav is not None:
            tk.Button(tips, text='Key Bindings Import in Settings', command=gui.show_settings,
                      bg=sidebar_bg, fg='#9fb3c6', activebackground=sidebar_bg, activeforeground='#eff7ff',
                      relief='flat', bd=0, padx=0, pady=2, anchor='w', cursor='hand2',
                      font=('Segoe UI', 9)).pack(anchor='w')
        window.protocol('WM_DELETE_WINDOW',gui.close)
        if on_ready is not None:
            window.update_idletasks()
            on_ready()
        window.after_idle(gui.show_connection_info_once)
        window.mainloop()
    finally:
        lobby.close()
        if 'gui' in locals() and gui.local_host is not None:
            gui.local_host.stop()

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
