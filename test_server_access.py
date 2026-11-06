import io
import json
from email.message import Message
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
import unittest
import urllib.error

from server_access import ServerAccess, NoRedirects, show_setup, bootstrap_payload
from server_access_contract import CONTRACT, endpoint_url, invite_url

URL = 'https://login.tailscale.com/admin/invite/example-test-code'
SETTINGS = dict(contract=CONTRACT, endpoint='https://server.example:8443/v1/server-access', enrollment_code='e' * 43)


class Response(io.BytesIO):
    status = 200
    def __init__(self, data):
        super().__init__(data)
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'


class AccessTests(unittest.TestCase):
    def test_bootstrap_uses_https_and_header_only_and_opens_only_valid_invites(self):
        calls, opened = [], []
        class Opener:
            def open(self, request, timeout):
                calls.append((request, timeout))
                return Response(json.dumps(dict(contract=CONTRACT, invite_url=URL)).encode())
        access = ServerAccess(SETTINGS, opener=Opener(), browser=lambda url: opened.append(url) or True)
        value = access.request_invite()
        access.open_invite(value)
        request, timeout = calls[0]
        self.assertEqual(request.full_url, SETTINGS['endpoint'])
        self.assertEqual(request.data, b'{}')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + SETTINGS['enrollment_code'])
        self.assertEqual(opened, [URL])

    def test_rejects_redirects_bad_responses_and_non_tailscale_destinations(self):
        self.assertIsNone(NoRedirects().redirect_request(None, None, 302, '', {}, 'https://other.example'))
        for value in ('http://server.example/v1/server-access', 'https://x:y@server.example/v1/server-access',
                      'https://server.example/v1/server-access?secret=example', 'https://server.example/other'):
            with self.assertRaises(ValueError): endpoint_url(value)
        for value in ('https://login.tailscale.com.evil.example/admin/invite/example-test-code',
                      URL + '?next=evil', URL + '#secret', 'file:///etc/passwd'):
            with self.assertRaises(ValueError): invite_url(value)
        for data in (b'[]', b'{}', b'x' * 4097,
                     json.dumps(dict(contract=CONTRACT, invite_url='https://other.example')).encode()):
            class Opener:
                def open(self, *_args, **_kwargs): return Response(data)
            with self.assertRaises(RuntimeError): ServerAccess(SETTINGS, opener=Opener()).request_invite()

    def test_rejected_credentials_do_not_leak_to_errors(self):
        class Opener:
            def open(self, request, **kwargs):
                raise urllib.error.HTTPError(request.full_url, 403, SETTINGS['enrollment_code'], {}, None)
        with self.assertRaisesRegex(RuntimeError, 'current client setup') as error:
            ServerAccess(SETTINGS, opener=Opener()).request_invite()
        self.assertNotIn(SETTINGS['enrollment_code'], str(error.exception))

    def test_absent_or_invalid_local_setup(self):
        with tempfile.TemporaryDirectory() as name:
            self.assertIsNone(ServerAccess.load(name))
            (Path(name) / 'server-access.json').write_text('[]')
            with self.assertRaises(ValueError): ServerAccess.load(name)

    def test_player_payload_rejects_operator_fields(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'settings.json'
            path.write_text(json.dumps(SETTINGS))
            self.assertEqual(json.loads(bootstrap_payload(path)), SETTINGS)
            path.write_text(json.dumps(dict(SETTINGS, token_file='private-api-token.txt')))
            with self.assertRaises(ValueError): bootstrap_payload(path)


class SetupWindowTests(unittest.TestCase):
    def test_invite_and_connect_without_changing_lobby_busy_state(self):
        from desktop_launcher import Desktop
        root = tk.Tk();root.withdraw()
        class Lobby:
            def capabilities(self): return {'connected': True}
        class FakeDesktop:
            access_window = None
            closing = False
            busy = True
            access_messages = queue.Queue()
            lobby = Lobby()
            button = Desktop.button
            def set_capabilities(self, value): self.received = value
        desktop = FakeDesktop();desktop.root = root
        opened = []
        class Access:
            browser = staticmethod(lambda url: True)
            def request_invite(self): return URL
            def open_invite(self, value): opened.append(value)
        try:
            show_setup(desktop, Access())
            window = desktop.access_window
            buttons = {child.cget('text'): child for child in window.winfo_children() if isinstance(child, tk.Button)}
            for label in ('2. Accept server access', '3. Check connection'):
                buttons[label].invoke()
                deadline = time.monotonic() + 3
                while desktop.access_messages.empty() and time.monotonic() < deadline:
                    root.update();time.sleep(.01)
                desktop.access_messages.get_nowait()()
            self.assertEqual(opened, [URL])
            self.assertTrue(desktop.received['connected'])
            self.assertTrue(desktop.busy)
            show_setup(desktop, Access())
            self.assertIs(desktop.access_window, window)
            buttons['Close'].invoke()
            self.assertIsNone(desktop.access_window)
        finally:
            root.destroy()


if __name__ == '__main__': unittest.main()
