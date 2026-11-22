
"""Read a signed server directory and present it in an independent Starter window."""
from pathlib import Path
import os
import queue
import threading
import time
import uuid

from directory_transport import directory_request, measure_ping, request_masters
from server_directory import (CACHE_SECONDS, DirectoryError, DirectoryIndex, HEX_ID, MAX_RESPONSE,
                              PROTOCOL_VERSION, canonical, read_json, verify_trust)


def _read(path, limit=MAX_RESPONSE + 65536):
    with Path(path).open('rb') as stream:
        return read_json(stream.read(limit + 1), limit=limit)


def _atomic(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as output:
            output.write(canonical(document))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ServerDirectory:
    def __init__(self, seed_path, local, *, clock=time.time, fetch=directory_request):
        self.clock, self.fetch = clock, fetch
        self.path = Path(local) / 'directory-browser.json'
        self.lock = threading.RLock()
        seed = _read(seed_path, 65536)
        if not isinstance(seed, dict) or set(seed) != {'root', 'trust'}:
            raise DirectoryError('Invalid Starter directory seed.')
        try:
            saved = _read(self.path)
            if not isinstance(saved, dict):
                saved = {}
        except (DirectoryError, OSError):
            saved = {}
        now = self.clock()
        root = seed['root']
        saved_feed = saved.get('feed')
        trusted = []
        for candidate in (seed['trust'], saved_feed.get('trust') if isinstance(saved_feed, dict) else None):
            try:
                trust = verify_trust(candidate, root, now, stale=CACHE_SECONDS)
            except DirectoryError:
                continue
            trusted.append((trust['revision'], candidate))
        if not trusted:
            raise DirectoryError('No valid signed Starter directory seeds remain.')
        _, trust = max(trusted, key=lambda entry: entry[0])
        self.index = DirectoryIndex(root, trust, now, cached=True)
        if saved_feed:
            try:
                self.index.absorb(saved_feed, now, cached=True)
            except DirectoryError:
                pass
        self.favourites = set(self._ids(saved.get('favourites')))
        self.history = list(self._ids(saved.get('history')))
        self.online = False

    @staticmethod
    def _ids(values):
        return tuple(dict.fromkeys(value for value in values[:256] if isinstance(value, str)
                                   and HEX_ID.fullmatch(value))) if isinstance(values, list) else ()

    def refresh(self):
        with self.lock:
            masters = tuple(self.index.trust_payload['masters'])
        worked = False
        for _, feed in request_masters(masters, fetch=self.fetch):
            with self.lock:
                try:
                    self.index.absorb(feed, self.clock())
                except DirectoryError:
                    continue
                worked = True
        with self.lock:
            self.online = worked
            if worked:
                self._save()

    def _save(self):
        _atomic(self.path, {'feed': self.index.feed(self.clock(), cached=True),
                           'favourites': sorted(self.favourites), 'history': self.history})

    def toggle_favourite(self, ident):
        with self.lock:
            if ident not in self.index.listings:
                return
            if ident in self.favourites:
                self.favourites.remove(ident)
            elif len(self.favourites) < 256:
                self.favourites.add(ident)
            self._save()

    def connected(self, ident):
        with self.lock:
            self.history = [ident, *(item for item in self.history if item != ident)][:256]
            self._save()

    def rows(self):
        with self.lock:
            rows = self.index.rows(self.clock(), cached=True)
            return [dict(row, favourite=row['server_id'] in self.favourites,
                         recent=row['server_id'] in self.history,
                         compatible=row['protocol'] == PROTOCOL_VERSION)
                    for row in rows if row['live'] or not self.online]


def filter_rows(rows, *, region='', full=False, locked=False, incompatible=False,
                favourites=False, recent=False):
    return [row for row in rows if (not region or row['region'] == region)
            and (not full or row['players'] < row['max_players'])
            and (not locked or not row['locked'])
            and (not incompatible or row['compatible'])
            and (not favourites or row['favourite'])
            and (not recent or row['recent'])]


class ServerBrowserWindow:
    def __init__(self, parent, directory, *, connect, on_connected):
        import tkinter as tk
        from tkinter import ttk
        from desktop_launcher import ACCENT, BG, MUTED, PANEL, TEXT

        self.directory, self.connect, self.on_connected = directory, connect, on_connected
        self.events = queue.Queue()
        self.pending = set()
        self.pings = {}
        self.targets = {}
        self.sort_key, self.descending = 'name', False
        self.window = tk.Toplevel(parent, background=BG)
        self.window.title('Community servers')
        self.window.geometry('1060x510')
        self.window.minsize(740, 400)
        frame = tk.Frame(self.window, background=BG, padx=22, pady=18)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text='Community servers', bg=BG, fg=TEXT, font=('Segoe UI', 23, 'bold')).pack(anchor='w')
        self.status = tk.StringVar()
        tk.Label(frame, textvariable=self.status, bg=BG, fg=MUTED, anchor='w', wraplength=850).pack(fill='x', pady=(3, 12))
        filters = tk.Frame(frame, bg=PANEL, padx=10, pady=7)
        filters.pack(fill='x', pady=(0, 9))
        self.region = ttk.Combobox(filters, state='readonly', width=16)
        self.region.pack(side='left', padx=(0, 12))
        self.region.bind('<<ComboboxSelected>>', lambda _event: self.render())
        self.region.set('All regions')
        self.flags = {}
        for key, label in (('full', 'Hide full'), ('locked', 'Hide locked'), ('incompatible', 'Compatible only'),
                           ('favourites', 'Favourites'), ('recent', 'History')):
            value = self.flags[key] = tk.BooleanVar()
            tk.Checkbutton(filters, text=label, variable=value, command=self.render, bg=PANEL, fg=TEXT,
                           selectcolor=BG, activebackground=PANEL, activeforeground=TEXT).pack(side='left')
        shell = ttk.Frame(frame)
        shell.pack(fill='both', expand=True)
        columns = (('name', 'Server', 185), ('region', 'Region', 85), ('map', 'Map', 135),
                   ('players', 'Players', 72), ('ping', 'Ping', 55), ('mode', 'Mode', 70),
                   ('locked', 'Access', 65), ('version', 'Version', 66), ('badge', 'Group', 155))
        self.columns = {key: title for key, title, _ in columns}
        self.table = ttk.Treeview(shell, columns=tuple(self.columns), show='headings', selectmode='browse')
        for key, _, width in columns:
            self.table.column(key, width=width, minwidth=45)
        scrollbar = ttk.Scrollbar(shell, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.table.pack(side='left', fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', lambda _: self.controls())
        self.table.bind('<Double-1>', lambda event: self.join() if self.table.identify_row(event.y) else None)
        actions = tk.Frame(frame, bg=BG)
        actions.pack(fill='x', pady=(12, 0))
        self.join_button = tk.Button(actions, text='Connect with invitation', command=self.join,
                                     bg=ACCENT, fg=BG, relief='flat', padx=14, pady=6)
        self.join_button.pack(side='left', padx=(0, 8))
        self.invitation_button = ttk.Button(actions, text='Use new invitation', command=lambda: self.join(replace=True))
        self.invitation_button.pack(side='left', padx=(0, 8))
        self.ping_button = ttk.Button(actions, text='Measure ping', command=self.ping)
        self.ping_button.pack(side='left', padx=(0, 8))
        self.favourite_button = ttk.Button(actions, text='Favourite', command=self.favourite)
        self.favourite_button.pack(side='left', padx=(0, 8))
        self.refresh_button = ttk.Button(actions, text='Refresh', command=self.refresh)
        self.refresh_button.pack(side='right')
        self.render()
        self.refresh()
        self.poll_handle = self.window.after(120, self.poll)
        self.window.bind('<Destroy>', self.stop_poll)

    def stop_poll(self, event):
        if event.widget is self.window and self.poll_handle is not None:
            self.window.after_cancel(self.poll_handle)
            self.poll_handle = None

    def submit(self, name, work):
        if name in self.pending:
            return
        self.pending.add(name)
        self.controls()
        def run():
            try:
                self.events.put((name, work(), None))
            except (DirectoryError, ValueError, OSError) as exc:
                self.events.put((name, None, str(exc)))
        threading.Thread(target=run, daemon=True, name='server-browser-' + name).start()

    def refresh(self):
        if 'refresh' not in self.pending:
            self.status.set('Refreshing. Saved servers remain visible.')
            self.submit('refresh', self.directory.refresh)

    def selected(self):
        selected = self.table.selection()
        return self.targets.get(selected[0]) if selected else None

    def controls(self):
        row = self.selected()
        usable = bool(row and row['live'])
        can_connect = bool(usable and row['compatible'] and 'connect' not in self.pending)
        for button in (self.join_button, self.invitation_button):
            button.configure(state='normal' if can_connect else 'disabled')
        self.ping_button.configure(state='normal' if usable and 'ping' not in self.pending else 'disabled')
        self.favourite_button.configure(state='normal' if row else 'disabled',
            text='Remove favourite' if row and row['favourite'] else 'Favourite')
        self.refresh_button.configure(state='disabled' if 'refresh' in self.pending else 'normal')

    def join(self, *, replace=False):
        row = self.selected()
        if 'connect' in self.pending:
            return
        if row and row['live'] and row['expires_at'] > self.directory.clock() and row['compatible']:
            self.connect(row, self, replace=replace)
        elif row:
            self.status.set('Refresh to verify that this server is still available.')

    def ping(self):
        row = self.selected()
        if row and row['live'] and row['expires_at'] > self.directory.clock():
            self.submit('ping', lambda: (row['server_id'], measure_ping(row)))

    def favourite(self):
        row = self.selected()
        if row:
            try:
                self.directory.toggle_favourite(row['server_id'])
            except OSError:
                self.status.set('Could not save your favourites.')
            self.render()

    def sort(self, key):
        self.descending = not self.descending if key == self.sort_key else False
        self.sort_key = key
        self.render()

    def render(self):
        selected = self.table.selection()
        rows = self.directory.rows()
        self.next_expiration = min((row['expires_at'] for row in rows if row['live']), default=float('inf'))
        regions = tuple(sorted({row['region'] for row in rows}, key=str.casefold))
        self.region.configure(values=('All regions', *regions))
        region = self.region.get()
        if region not in regions:
            region = ''
            self.region.set('All regions')
        rows = filter_rows(rows, region=region, **{key: value.get() for key, value in self.flags.items()})
        self.targets = {row['server_id']: row for row in rows}
        for key,title in self.columns.items():
            direction = ('  ↓' if self.descending else '  ↑') if key == self.sort_key else ''
            self.table.heading(key, text=title + direction, command=lambda item=key: self.sort(item))
        for row in rows:
            row['ping'] = self.pings.get(row['server_id'])
            row['badge'] = ', '.join(badge['name'] for badge in row['badges'])
        known = [row for row in rows if row.get(self.sort_key) is not None]
        known.sort(key=lambda row: row[self.sort_key].casefold() if isinstance(row[self.sort_key], str)
                   else row[self.sort_key], reverse=self.descending)
        children = self.table.get_children()
        if children:
            self.table.delete(*children)
        for row in (*known, *(row for row in rows if row.get(self.sort_key) is None)):
            count = f'{row["players"]} / {row["max_players"]}' if row['live'] else 'Cached'
            version = row['version'] if row['compatible'] else row['version'] + ' · incompatible'
            self.table.insert('', 'end', iid=row['server_id'], values=(
                ('★ ' if row['favourite'] else '') + row['name'], row['region'], row['map'], count,
                f'{row["ping"]} ms' if row['ping'] is not None else '—', row['mode'].title(),
                'Locked' if row['locked'] else 'Open', version, row['badge'] or '—'))
        if selected and selected[0] in self.targets:
            self.table.selection_set(selected[0])
        self.controls()

    def poll(self):
        self.poll_handle = None
        try:
            while True:
                name, value, error = self.events.get_nowait()
                self.pending.discard(name)
                if error:
                    self.status.set(error)
                elif name == 'refresh':
                    self.status.set('Choose an invitation or measure ping for a server.' if self.directory.online
                                    else 'No master answered. Showing the last saved directory.')
                elif name == 'connect':
                    self.on_connected(value)
                    return
                elif name == 'ping':
                    ident, latency = value
                    self.pings[ident] = latency
                    self.status.set(f'Direct TLS response in {latency} ms.')
                self.render()
        except queue.Empty:
            pass
        if self.directory.clock() >= self.next_expiration:
            self.render()
        self.poll_handle = self.window.after(120, self.poll)
