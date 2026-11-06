"""HTTPS bootstrap for players who cannot reach the private lobby yet."""
import json
from pathlib import Path
import urllib.error
import urllib.request
import webbrowser

from server_access_contract import CONTRACT, MAX_RESPONSE, endpoint_url, enrollment_code, invite_url

DOWNLOAD_URL = 'https://tailscale.com/download/windows'


def bootstrap_payload(path):
    """Only these three player-facing fields may enter a player package."""
    raw = Path(path).read_bytes()
    if len(raw) > MAX_RESPONSE:
        raise ValueError('Invalid server-access configuration.')
    settings = json.loads(raw)
    if not isinstance(settings, dict) or set(settings) != {'contract', 'endpoint', 'enrollment_code'}:
        raise ValueError('Player setup must not contain operator settings or API credentials.')
    ServerAccess(settings)
    return (json.dumps(settings, indent=2) + '\n').encode()


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ServerAccess:
    def __init__(self, settings, *, opener=None, browser=None):
        if not isinstance(settings, dict) or settings.get('contract') != CONTRACT:
            raise ValueError('Unsupported server-access configuration.')
        self.endpoint = endpoint_url(settings.get('endpoint'))
        self.code = enrollment_code(settings.get('enrollment_code'))
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirects())
        self.browser = browser or webbrowser.open

    @classmethod
    def load(cls, package):
        path = Path(package) / 'server-access.json'
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_RESPONSE:
            raise ValueError('Invalid server-access configuration.')
        return cls(json.loads(path.read_bytes()))

    def request_invite(self):
        request = urllib.request.Request(self.endpoint, data=b'{}', method='POST', headers={
            'Authorization': 'Bearer ' + self.code,
            'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=12) as response:
                if response.status != 200 or response.headers.get_content_type() != 'application/json':
                    raise ValueError()
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError()
                value = json.loads(raw)
                if not isinstance(value, dict) or value.get('contract') != CONTRACT:
                    raise ValueError()
                return invite_url(value.get('invite_url'))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError('This client’s server-access code is no longer accepted. Ask for the current client setup.') from None
            if exc.code == 429:
                raise RuntimeError('Server setup is busy. Try again in a minute.') from None
            raise RuntimeError('Server access is temporarily unavailable. Try again shortly.') from None
        except (OSError, ValueError, urllib.error.URLError):
            raise RuntimeError('Could not reach server setup securely. Check your internet connection and try again.') from None

    def open_invite(self, value):
        if not self.browser(invite_url(value)):
            raise RuntimeError('Could not open your browser. Check your default browser and try again.')


def show_setup(desktop, access):
    """Keep all network work off Tk's thread and preserve the existing lobby."""
    import tkinter as tk
    if getattr(desktop, 'access_window', None) is not None:
        desktop.access_window.lift()
        return
    window = tk.Toplevel(desktop.root)
    desktop.access_window = window
    window.title('Set up server access')
    window.configure(bg='#132335')
    window.resizable(False, False)
    status = tk.StringVar(value='Install Tailscale and sign in with your own account, then accept access to the game server.')
    tk.Label(window, text='Connect once. Play together.', bg='#132335', fg='#eff7ff',
             font=('Segoe UI', 17, 'bold')).pack(anchor='w', padx=24, pady=(22, 10))
    tk.Label(window, textvariable=status, wraplength=430, justify='left', bg='#132335',
             fg='#9fb3c6', font=('Segoe UI', 11)).pack(anchor='w', padx=24, pady=(0, 18))
    buttons = []
    pending = False

    def close():
        desktop.access_window = None
        window.destroy()

    def complete(callback, value=None, error=None):
        nonlocal pending
        pending = False
        if desktop.closing or desktop.access_window is not window:
            return
        for button in buttons:
            button.configure(state='normal')
        if error is not None:
            status.set(str(error))
        else:
            callback(value)

    def work(fn, callback):
        nonlocal pending
        if pending:
            return
        pending = True
        for button in buttons:
            button.configure(state='disabled')
        import threading
        def execute():
            try:
                value = fn()
            except Exception as exc:
                desktop.access_messages.put(lambda exc=exc: complete(callback, error=exc))
            else:
                desktop.access_messages.put(lambda: complete(callback, value=value))
        threading.Thread(target=execute, daemon=True).start()

    def accepted(value):
        try:
            access.open_invite(value)
            status.set('Accept the server invitation in your browser. Keep Tailscale connected, then select Check connection below.')
        except RuntimeError as exc:
            status.set(str(exc))

    def checked(value):
        desktop.set_capabilities(value)
        status.set('Connected to the game server. You can close this window and create or join a lobby.')

    for text, command in (
            ('1. Install Tailscale', lambda: access.browser(DOWNLOAD_URL)),
            ('2. Accept server access', lambda: work(access.request_invite, accepted)),
            ('3. Check connection', lambda: work(desktop.lobby.capabilities, checked))):
        button = desktop.button(window, text, command)
        button.pack(fill='x', padx=24, pady=(0, 10))
        buttons.append(button)
    desktop.button(window, 'Close', close, False).pack(anchor='e', padx=24, pady=(4, 20))
    window.protocol('WM_DELETE_WINDOW', close)
