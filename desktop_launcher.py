"""Development-only Community Starter lobby and owned game launcher."""
from array import array
from collections import deque
from operator import itemgetter
import base64
import tempfile
import argparse
import json
import os
import webbrowser
import logging
from pathlib import Path
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from urllib.parse import parse_qs, urlsplit

from community_game import CommunityGame
from startup_paths import installation_options, local_directory
from community_transport import CommunityClient, CommunityError, CommunityConnectionError, DEFAULT_LOBBY_RULES, MAX_LOBBY_BOTS
from community_maps import BY_ID, options, read_options, LEGACY_MAPS
from map_sync_contract import CATALOG_VERSION, SESSION_VERSION, valid_sha
from player_names import display_name
from steam_identity import SteamIdentityError, read_local_name, save_local_name

def normalize_lobby_code(value):
    value = re.sub(r'^lobby\s+code\s*:\s*', '', value.strip(), flags=re.IGNORECASE)
    if '://' in value:
        try:
            invite = urlsplit(value)
            codes = parse_qs(invite.query, max_num_fields=20).get('code')
        except ValueError:
            return None
        segments = invite.path.strip('/').split('/')
        if invite.scheme.lower() == 't3' and invite.netloc.lower() == 'join' and len(segments) == 1:
            value = segments[0]
        elif invite.scheme.lower() in ('http', 'https') and invite.hostname:
            if codes and len(codes) == 1:
                value = codes[0]
            elif len(segments) >= 2 and segments[-2].lower() == 'join':
                value = segments[-1]
            else:
                return None
        else:
            return None
    value = value.upper()
    return value if re.fullmatch(r'[A-Z2-9]{6}', value) else None


ROOT = Path(__file__).resolve().parent
CLIENT_PACKAGE = ROOT if (ROOT / 'connection-policy.json').is_file() else ROOT / 'dynamic-client-development'
APP_TITLE = 'Tribes 3 Mod Community Edition: Phoenix Rising'
NOTICE_MS = 10000
TEAM_NAMES = {'blue': 'Children of The Phoenix', 'red': 'Diamond Sword'}
BG, PANEL, TEXT, MUTED, ACCENT = '#0a111b', '#132335', '#eff7ff', '#9fb3c6', '#4be4c1'


# The signed updater distributes inventoried modules. Its build embeds the artwork here.
PHOENIX_ART = {}


def art_bytes(name):
    if name in PHOENIX_ART:
        return base64.b85decode(PHOENIX_ART[name])
    return (ROOT / 'branding' / name).read_bytes()


def art_photo(root, name):
    return tk.PhotoImage(master=root, data=art_bytes(name), format='png')


def set_phoenix_icon(root, icon):
    root.iconphoto(True, icon)
    if sys.platform == 'win32':
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'phoenix.ico'
            path.write_bytes(art_bytes('phoenix.ico'))
            root.iconbitmap(str(path))


class PhoenixBackdrop:
    """Paint matching portions of one cover-scaled image into Tk's opaque frames."""
    def __init__(self, root):
        self.root = root
        image = art_photo(root, 'phoenix-world.png')
        rgb = root.tk.call(str(image), 'data', '-format', 'ppm').split(b'\n', 3)[3]
        packed = bytearray(image.width() * image.height() * 4)
        for channel in range(3):
            packed[channel::4] = rgb[channel::3]
        pixels = array('I')
        pixels.frombytes(packed)
        self.source = [pixels[i:i+image.width()] for i in range(0, len(pixels), image.width())]
        self.layers = {}
        self.regions = {}
        self.rows = []
        self.size = None
        self.pending = None
        self.closed = False
        self.attach(root)
        root.bind('<Configure>', self.changed, add='+')
        root.bind('<Map>', self.changed, add='+')
        root.bind('<Destroy>', self.destroyed, add='+')

    def attach(self, frame, tint=0):
        image = tk.Label(frame, bd=0, highlightthickness=0, anchor='nw', takefocus=False, bg=BG)
        image.place(x=0, y=0, relwidth=1, relheight=1, bordermode='outside')
        image.lower()
        self.layers[frame] = (image, tint, None)

    def logo(self, label, emblem):
        self.layers[label] = (label, .80, emblem)

    def canvas(self, widget, item):
        self.layers[widget] = (widget, 0, item)

    def changed(self, event):
        if self.closed:
            return
        widget = event.widget
        # Public CTF and Armor are supplied by the Direct client after Desktop starts.
        if isinstance(widget, tk.Frame) and widget.master is self.root and widget not in self.layers:
            self.attach(widget, .60)
        if widget in self.layers and self.pending is None:
            self.pending = self.root.after_idle(self.paint)

    def scale(self, width, height):
        sw, sh = len(self.source[0]), len(self.source)
        scale = max(width / sw, height / sh)
        top = (sh - height / scale) / 2
        columns = [min(sw-1, int((x+.5)/scale)) for x in range(width)]
        select = itemgetter(*columns)
        self.rows = []
        last_y = -1
        for y in range(height):
            source_y = min(sh-1, int(top + (y+.5)/scale))
            if source_y != last_y:
                rgba = array('I', select(self.source[source_y])).tobytes()
                row = bytearray(width * 3)
                for channel in range(3):
                    row[channel::3] = rgba[channel::4]
                last_y = source_y
            # Fade the foot of the image to keep the lobby status legible.
            shade = max(0, (y / height - .57) / .43) * .58
            self.rows.append(row.translate(self.table(shade)) if shade else row)

    @staticmethod
    def table(shade):
        return bytes(round(v * (1 - shade) + 16 * shade) for v in range(256))

    def paint(self):
        self.pending = None
        width, height = self.root.winfo_width(), self.root.winfo_height()
        if width < 2 or height < 2 or not self.root.winfo_viewable():
            return
        if self.size != (width, height):
            self.scale(width, height)
            self.size = (width, height)
            self.regions.clear()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        for widget, (target, tint, overlay) in self.layers.items():
            if not widget.winfo_viewable():
                continue
            x, y = widget.winfo_rootx() - rx, widget.winfo_rooty() - ry
            w, h = widget.winfo_width(), widget.winfo_height()
            if self.regions.get(widget) == (x,y,w,h):
                continue
            if x < 0 or y < 0 or x+w > width or y+h > height:
                continue
            raw = b''.join(row[3*x:3*(x+w)] for row in self.rows[y:y+h])
            if tint:
                raw = raw.translate(self.table(tint))
            photo = tk.PhotoImage(master=self.root, data=f'P6\n{w} {h}\n255\n'.encode() + raw, format='ppm')
            if isinstance(target, tk.Canvas):
                target.itemconfigure(overlay, image=photo)
            else:
                if overlay is not None:
                    self.root.tk.call(str(photo), 'copy', str(overlay), '-to', (w-overlay.width())//2,
                                      (h-overlay.height())//2, '-compositingrule', 'overlay')
                target.configure(image=photo)
            target._phoenix_photo = photo
            self.regions[widget] = (x,y,w,h)

    def destroyed(self, event):
        if event.widget is self.root:
            self.close()
        else:
            self.layers.pop(event.widget, None)
            self.regions.pop(event.widget, None)

    def close(self):
        self.closed = True
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None


def starter_version(package=ROOT):
    try:
        manifest = json.loads((package / 'package-manifest.json').read_bytes())
        if isinstance(manifest, dict):
            revision = manifest.get('starter_update_revision')
            if type(revision) is int and revision > 0:
                return f'Build r{revision}'
            release = manifest.get('release_id')
            if isinstance(release, str) and release.strip():
                return f'Build {release}'
    except (OSError, ValueError):
        pass
    return 'Base build'


def match_phase_text(room):
    if room is None:
        return 'Create a lobby or enter a code.'
    restart = room.get('restart')
    if isinstance(restart, dict):
        stage = restart.get('stage')
        reason = restart.get('reason', '')
        if stage == 'countdown':
            return f"Restarting in {restart.get('seconds', 0)}s · {reason}"
        if stage == 'checkpointing':
            return f'Saving current score and time · {reason}'
        if stage == 'restoring':
            return f'Waiting for players to load before restoring the score and clock · {reason}'
        if stage in ('draining', 'starting') or stage == 'complete' and room['phase'] == 'starting':
            progress = (room.get('match') or {}).get('progress') if restart.get('replacementMatchId') else None
            text = f'Match restarting · {reason}'
            return text + f' — {progress.strip()}' if isinstance(progress, str) and progress.strip() else text
        if stage == 'failed':
            return 'Restart failed · ' + restart.get('error', 'Try again.')
    text = 'Match: ' + room['phase']
    if room['phase']=='setup':
        preparation=room.get('preparation')
        if isinstance(preparation,dict):
            label={'waiting':'Waiting for a server slot…','preparing':'Preparing the selected map…',
                   'ready':'Server ready. Choose teams, then start.','stopping':'Changing the prepared map…',
                   'failed':'Server preparation failed; Start match can retry.'}.get(preparation.get('status'))
            if label:text+=' — '+(preparation.get('progress') or label)
    if room['phase'] in ('starting', 'ready'):
        match = room.get('match')
        progress = match.get('progress') if isinstance(match, dict) else None
        if isinstance(progress, str) and progress.strip():
            text += ' — ' + progress.strip()
    return text


class Desktop:
    def __init__(self, root, lobby, game_factory, *, steam_name_loader=None, server_access=None, map_sync=None,
                 name_settings_dir=None):
        self.root, self.lobby, self.game_factory = root, lobby, game_factory
        self.steam_name_loader = steam_name_loader
        name_settings = Path(name_settings_dir) if name_settings_dir is not None else local_directory()
        self.warrior_name_path = name_settings / 'warrior-name.json'
        self.steam_name_path = name_settings / 'steam-persona.json'
        self.warrior_name = read_local_name(self.warrior_name_path) if steam_name_loader else ''
        self.steam_name = read_local_name(self.steam_name_path) if steam_name_loader else ''
        self.steam_messages = queue.Queue()
        self.steam_lookup_running = False
        self.steam_lookup_error = None
        self.steam_lookup_at = 0
        self.steam_retry_handle = None
        self.map_sync = map_sync
        self.maps_panel = None
        self.lobby_map_target = None
        self.game = None
        self.room = None
        self.pending_map = None
        self.map_inflight = None
        self.map_retry_count = 0
        self.map_retry_at = 0
        self.watch_id = None
        self.game_status = 'idle'
        self.last_game_error = None
        self.last_preparation_error = None
        self.shown_game_error = None
        self.join_attempted_match = None
        self.current_panel = 'lobbies'
        self.live_targets = {}
        self.caps = {'matchStartEnabled': False, 'gameClientReady': False}
        self.capabilities_loaded = False
        self.busy = False
        self.background_busy = False
        self.queued_action = None
        self.messages = queue.Queue()
        self.access_messages = queue.Queue()
        self.access_window = None
        self.settings_window = None
        self.players = []
        self.closing = False
        self.copy_reset_handle = None
        self.notice_timers = {}
        self.ignore_departed_game_notices = False
        self.last_map_notice = None
        root.title(APP_TITLE)
        # Previously distributed BAT wrappers set a legacy title after Desktop returns.
        root.after_idle(root.title, APP_TITLE)
        root.geometry('1030x800')
        root.minsize(850, 740)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TCombobox', fieldbackground='#20374a', background='#20374a', foreground=TEXT, arrowcolor=ACCENT, padding=8)
        style.map(
            'TCombobox',
            fieldbackground=[('disabled', '#192c3d'), ('readonly', '#20374a')],
            foreground=[('disabled', '#a9c1d4'), ('readonly', TEXT)],
            selectbackground=[('readonly', '#31566c')],
            selectforeground=[('readonly', TEXT)],
        )
        root.option_add('*TCombobox*Listbox.background', '#182c3d', 'widgetDefault')
        root.option_add('*TCombobox*Listbox.foreground', TEXT, 'widgetDefault')
        root.option_add('*TCombobox*Listbox.selectBackground', '#31566c', 'widgetDefault')
        root.option_add('*TCombobox*Listbox.selectForeground', TEXT, 'widgetDefault')
        root.option_add('*TCombobox.font', '{Segoe UI} 11', 'widgetDefault')
        root.option_add('*TCombobox*Listbox.font', '{Segoe UI} 11', 'widgetDefault')
        style.configure('Live.Treeview',background='#0b1a29',fieldbackground='#0b1a29',foreground=TEXT,
                        rowheight=28,font=('Segoe UI',10))
        style.configure('Live.Treeview.Heading',background='#20374a',foreground=TEXT,font=('Segoe UI',9,'bold'))
        style.map('Live.Treeview',background=[('selected','#31566c')])
        self.name = tk.StringVar(value=self.warrior_name or self.steam_name)
        self.code = tk.StringVar()
        self.map_name = tk.StringVar(value='Stonehenge')
        self.status = tk.StringVar(value='Checking community service…')
        self.room_heading = tk.StringVar(value='Not in a lobby')
        self.phase = tk.StringVar(value='Create a lobby or enter a code.')
        self.preparation = tk.StringVar(value='')
        self.watch_notice(self.status)
        self.watch_notice(self.preparation)
        self.allow_spectators = tk.BooleanVar(value=True)
        self.flag_indicators = tk.BooleanVar(value=False)
        self.fall_damage = tk.BooleanVar(value=False)
        self.allow_bots = tk.BooleanVar(value=False)
        self.bot_count = tk.StringVar(value='2')
        self.retail_capture_point = tk.BooleanVar(value=True)
        self.live_status = tk.StringVar(value='Checking live matches…')
        side = tk.Frame(root, bg='#0d1927', width=225)
        self.sidebar = side
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        self.backdrop = PhoenixBackdrop(root)
        self.backdrop.attach(side, .80)
        self.app_icon = art_photo(root, 'phoenix-icon.png')
        root.after_idle(set_phoenix_icon, root, self.app_icon)
        self.emblem = art_photo(root, 'phoenix-emblem.png')
        logo = tk.Label(side, image=self.emblem, width=self.emblem.width(), height=self.emblem.height(),
                        borderwidth=0, highlightthickness=0, bg='#0d1927')
        logo.pack(pady=(12, 14))
        self.backdrop.logo(logo, self.emblem)
        self.lobbies_nav = self.button(side, 'PLAY', lambda: self.show_panel('lobbies'), False)
        self.lobbies_nav.configure(anchor='center', bg='#237939', fg=TEXT, activebackground='#19632d',
                                   activeforeground=TEXT, font=('Segoe UI', 11, 'bold'))
        self.lobbies_nav.pack(fill='x',padx=18,pady=(0,6))
        self.live_nav=self.button(side,'Lobby Browser',lambda:self.show_panel('live'),False)
        self.live_nav.pack(fill='x',padx=18)
        if self.map_sync is not None:
            self.button(side, 'Maps', lambda: self.show_panel('maps'), False).pack(fill='x', padx=18, pady=(6, 0))
        if server_access is not None:
            from server_access import show_setup
            self.access_button = self.button(side, 'Set up server access', lambda: show_setup(self, server_access), False)
            self.access_button.pack(fill='x', padx=18, pady=(20, 0))
        self.label(side, starter_version(), 10, color=MUTED, bg='#0d1927').pack(side='bottom', anchor='w', padx=26, pady=24)
        tk.Label(side,textvariable=self.preparation,bg='#0d1927',fg=MUTED,font=('Segoe UI',10),
                 anchor='w',justify='left',wraplength=175).pack(side='bottom',anchor='w',padx=26,pady=(0,12))
        if self.map_sync is not None:
            self.map_status = tk.StringVar(value='')
            self.watch_notice(self.map_status)
            tk.Label(side,textvariable=self.map_status,bg='#0d1927',fg=MUTED,font=('Segoe UI',10),
                     anchor='w',justify='left',wraplength=175).pack(side='bottom',anchor='w',padx=26,pady=(0,12))
            self.map_progress = ttk.Progressbar(side, mode='determinate')
        self.settings_nav = None
        if sys.platform == 'win32':
            self.settings_nav = self.button(side, 'Settings', self.show_settings, False)
            self.settings_nav.pack(fill='x', padx=18, pady=(6, 0))
        else:
            self.button(side, 'About this launcher', self.show_connection_info, False).pack(
                fill='x', padx=18, pady=(6, 0))
        main = tk.Frame(root, bg=BG)
        self.lobby_panel=main
        main.pack(side='left', fill='both', expand=True, padx=32, pady=20)
        self.backdrop.attach(main)
        self.hero = tk.Canvas(main, bg=BG, height=64, highlightthickness=0, borderwidth=0)
        self.hero.pack(fill='both', expand=True, pady=(0, 10))
        self.hero_scene = self.hero.create_image(0, 0, anchor='nw')
        self.backdrop.canvas(self.hero, self.hero_scene)
        self.lobby_layout = None
        entry = tk.Frame(main, bg=PANEL, padx=18, pady=14)
        entry.pack(fill='x')
        self.label(entry, 'LOBBY CODE', 9, color=ACCENT, bg=PANEL).grid(row=0, column=0, sticky='w')
        code_field = tk.Frame(entry, bg=PANEL)
        code_field.grid(row=1, column=0, sticky='ew', pady=(4, 8))
        self.code_entry = tk.Entry(code_field, textvariable=self.code, font=('Segoe UI',12), bg='#20374a',
                                   fg=TEXT, insertbackground=TEXT, relief='flat', width=8)
        self.code_entry.pack(side='left', fill='both', expand=True, ipady=7)
        self.paste_code_button = self.button(code_field, 'Paste', self.paste_lobby_code, False)
        self.paste_code_button.pack(side='right', padx=(6,0))
        self.code_entry.bind('<<Paste>>', self.paste_lobby_code)
        self.code_entry.bind('<Button-3>', self.open_lobby_code_menu)
        self.code_menu = tk.Menu(self.code_entry, tearoff=False)
        self.code_menu.add_command(label='Paste', command=self.paste_lobby_code)
        self.code_menu.add_command(label='Cut', command=lambda: self.code_entry.event_generate('<<Cut>>'))
        self.code_menu.add_command(label='Copy', command=lambda: self.code_entry.event_generate('<<Copy>>'))
        self.code_menu.add_command(label='Select All', command=lambda: self.code_entry.selection_range(0, tk.END))
        self.code_menu.add_command(label='Clear', command=lambda: self.code.set(''))
        self.label(entry, 'PLAYER NAME' if steam_name_loader else 'YOUR PLAYER NAME', 9,
                   color=ACCENT, bg=PANEL).grid(row=0, column=1, sticky='w', padx=(12, 0))
        self.name_entry = tk.Entry(entry, textvariable=self.name, width=23, font=('Segoe UI', 12),
                                   bg='#20374a', fg=TEXT, insertbackground=TEXT, relief='flat')
        self.name_entry.grid(row=1, column=1, sticky='ew', padx=(12, 0), ipady=7, pady=(4, 8))
        self.join_button = self.button(entry, 'Join lobby', self.join, False)
        self.join_button.grid(row=2, column=0, sticky='w')
        self.lobby_create_button = self.button(entry, 'Create lobby', self.create)
        self.lobby_create_button.grid(row=2, column=1, sticky='w', padx=(12, 0))
        entry.columnconfigure(1, weight=2)
        self.lock_lobby = tk.BooleanVar(value=False)
        self.lobby_match_type = tk.StringVar(value='Standard')
        self.lobby_type_row = tk.Frame(entry, bg=PANEL)
        self.label(self.lobby_type_row, 'MATCH TYPE', 9, color=ACCENT, bg=PANEL).pack(side='left', padx=(0, 8))
        self.lobby_type_picker = self.match_type_picker(self.lobby_type_row)
        self.lobby_type_picker.pack(side='left')
        self.lobby_lock = tk.Checkbutton(entry, text='Lock lobby after start', variable=self.lock_lobby,
            bg=PANEL, fg=TEXT, selectcolor='#20374a', activebackground=PANEL, activeforeground=TEXT)
        self.backdrop.attach(entry, .83)
        self.entry_panel = entry
        self.retail_import_row = None
        self.retail_import_complete = None
        self.entry_map_label = self.label(entry, 'STARTING MAP', 9, color=ACCENT, bg=PANEL)
        self.entry_map = ttk.Combobox(entry, width=18, state='disabled')
        entry.columnconfigure(2, weight=1)
        card = self.room_card = tk.Frame(main,bg=PANEL,padx=18,pady=14)
        card.pack(fill='both',expand=True,pady=(14,0))
        heading = tk.Frame(card,bg=PANEL)
        heading.pack(fill='x')
        self.copy_code_button = self.button(heading,'Copy lobby code',self.copy_lobby_code,False)
        self.copy_code_button.pack(side='right',padx=(12,0))
        tk.Label(heading,textvariable=self.room_heading,bg=PANEL,fg=TEXT,font=('Segoe UI',17,'bold'),anchor='w').pack(side='left',fill='x',expand=True)
        tk.Label(card,textvariable=self.phase,bg=PANEL,fg=MUTED,font=('Segoe UI',10),anchor='w').pack(fill='x',pady=(2,8))
        maprow = tk.Frame(card,bg=PANEL);maprow.pack(fill='x')
        self.label(maprow,'MAP',9,color=ACCENT,bg=PANEL).pack(side='left',padx=(0,12))
        self.map_options=sorted(options(LEGACY_MAPS), key=lambda item: item['label'].casefold())
        self.map_combo = ttk.Combobox(maprow,textvariable=self.map_name,values=tuple(item['label'] for item in self.map_options),state='disabled')
        self.map_combo.pack(side='left',fill='x',expand=True)
        self.map_combo.bind('<<ComboboxSelected>>',lambda e:self.choose_map())
        self.spectator_toggle=tk.Checkbutton(maprow,text='Allow spectators',variable=self.allow_spectators,
            command=self.toggle_spectators,bg=PANEL,fg=TEXT,selectcolor='#20374a',activebackground=PANEL,
            activeforeground=TEXT,font=('Segoe UI',9))
        self.side_row = tk.Frame(card, bg=PANEL)
        self.label(self.side_row, 'PHOENIX STARTING SIDE', 9, color=ACCENT, bg=PANEL).pack(side='left', padx=(0, 8))
        self.blue_side = tk.StringVar(value='Side A')
        self.side_combo = ttk.Combobox(self.side_row, textvariable=self.blue_side,
                                       values=('Side A', 'Side B'), width=8, state='disabled')
        self.side_combo.pack(side='left')
        self.side_combo.bind('<<ComboboxSelected>>', self.choose_side)
        self.red_side = tk.StringVar(value='Diamond Sword starts on Side B')
        tk.Label(self.side_row, textvariable=self.red_side, bg=PANEL, fg=MUTED).pack(side='left', padx=10)
        roster_frame = self.roster_frame = tk.Frame(card,bg=PANEL)
        roster_frame.pack(fill='both',expand=True,pady=(8,4))
        self.rules_row = tk.Frame(card,bg=PANEL)
        check_style = dict(bg=PANEL,fg=TEXT,selectcolor='#20374a',activebackground=PANEL,
                           activeforeground=TEXT,font=('Segoe UI',9))
        self.flag_toggle = tk.Checkbutton(self.rules_row,text='Flag indicators',variable=self.flag_indicators,
            command=lambda:self.call_action('rules',flagIndicators=self.flag_indicators.get()),**check_style)
        self.flag_toggle.pack(side='left')
        self.fall_toggle = tk.Checkbutton(self.rules_row, text='Fall damage', variable=self.fall_damage,
            command=lambda: self.call_action('rules', fallDamage=self.fall_damage.get()), **check_style)
        self.bot_toggle = tk.Checkbutton(self.rules_row,text='Allow bots',variable=self.allow_bots,
            command=self.change_bots,**check_style)
        self.bot_toggle.pack(side='left',padx=(10,0))
        self.bot_spinner = ttk.Spinbox(self.rules_row,from_=1,to=MAX_LOBBY_BOTS,textvariable=self.bot_count,
                                       width=3,state='disabled',command=self.change_bots)
        self.bot_spinner.pack(side='left',padx=(2,10))
        self.capture_toggle = tk.Checkbutton(self.rules_row,text='Retail capture point',variable=self.retail_capture_point,
            command=lambda:self.call_action('rules',retailCapturePoint=self.retail_capture_point.get()),**check_style)
        self.capture_toggle.pack(side='left')
        self.rosters = {}
        self.roster_players = {}
        roster_frame.columnconfigure((0, 1), weight=1, uniform='teams')
        roster_frame.rowconfigure(0, weight=1)
        for team, label, color, col in (('blue', TEAM_NAMES['blue'], '#78b8ff', 0),
                                         ('red', TEAM_NAMES['red'], '#ff9393', 1),
                                         (None, 'Unassigned', MUTED, 0)):
            frame = tk.Frame(roster_frame, bg=PANEL)
            frame.grid(row=1 if team is None else 0, column=col, columnspan=2 if team is None else 1,
                       sticky='nsew', padx=(0, 6) if team == 'blue' else (0, 0))
            self.label(frame, label, 10, True, color=color, bg=PANEL).pack(anchor='w')
            roster = tk.Listbox(frame, bg='#0b1a29', fg=TEXT, selectbackground='#31566c',
                                font=('Segoe UI', 11), relief='flat', width=1,
                                height=1 if team is None else 4, exportselection=False)
            scroll = ttk.Scrollbar(frame, orient='vertical', command=roster.yview)
            roster.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            roster.pack(side='left', fill='both', expand=True)
            roster.bind('<<ListboxSelect>>', lambda _event, box=roster: self.select_roster(box))
            self.rosters[team] = roster
            self.roster_players[team] = []
        teams = tk.Frame(card,bg=PANEL);teams.pack(side='bottom',before=roster_frame,fill='x')
        self.blue_button = self.button(teams,'Join Phoenix',lambda:self.call_action('team',team='blue'),False);self.blue_button.pack(side='left',padx=(0,8))
        self.red_button = self.button(teams,'Join Diamond Sword',lambda:self.call_action('team',team='red'),False);self.red_button.pack(side='left',padx=(0,8))
        self.move_blue = self.button(teams,'Move to Phoenix',lambda:self.move('blue'),False);self.move_blue.pack(side='left',padx=(0,8))
        self.move_red = self.button(teams,'Move to Diamond Sword',lambda:self.move('red'),False);self.move_red.pack(side='left')
        actions = tk.Frame(main,bg=BG);actions.pack(side='bottom',before=card,fill='x',pady=(14,0))
        self.room_actions = actions
        self.start_button = self.button(actions,'Start match',lambda:self.call_action('start'));self.start_button.pack(side='left',padx=(0,8))
        self.game_button = self.button(actions,'Join game',self.join_game);self.game_button.pack(side='left',padx=(0,8))
        self.stop_button = self.button(actions,'Stop match',lambda:self.call_action('stop'),False);self.stop_button.pack(side='left',padx=(0,8))
        self.restart_button = self.button(actions, 'Restart match', self.restart_match, False)
        self.reset_button = self.button(actions,'New setup',lambda:self.call_action('reset'),False);self.reset_button.pack(side='left',padx=(0,8))
        self.leave_button = self.button(actions,'Exit lobby',self.exit_lobby,False);self.leave_button.pack(side='left')
        tk.Label(main,textvariable=self.status,bg=BG,fg=MUTED,font=('Segoe UI',10),anchor='w',wraplength=700).pack(side='bottom',before=actions,anchor='w',pady=(12,0))
        self.live_panel=tk.Frame(root,bg=BG)
        self.label(self.live_panel,'Lobby Browser',27,True).pack(anchor='w')
        self.live_summary=self.label(self.live_panel,'Left click for next player, right click for previous. F7 for first person, F8 for chase, or middle click to switch views.',
                   11,color=MUTED)
        self.live_summary.configure(wraplength=500,justify='left')
        self.live_summary.pack(anchor='w',pady=(4,18))
        create_card = tk.Frame(self.live_panel, bg=PANEL, padx=14, pady=12)
        create_card.pack(fill='x', pady=(0, 12))
        self.create_map_name = tk.StringVar()
        self.entry_map.configure(textvariable=self.create_map_name)
        self.browser_name = tk.Entry(create_card, textvariable=self.name, width=16, bg='#20374a',
                                     fg=TEXT, insertbackground=TEXT, relief='flat')
        self.browser_name.pack(side='left', ipady=6, padx=(0, 8))
        self.create_map = ttk.Combobox(create_card, textvariable=self.create_map_name, state='disabled')
        self.create_map.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.create_button = self.button(create_card, 'Create lobby', self.create)
        self.create_button.pack(side='right')
        self.browser_lock = tk.Checkbutton(create_card, text='Lock lobby', variable=self.lock_lobby,
            bg=PANEL, fg=TEXT, selectcolor='#20374a', activebackground=PANEL, activeforeground=TEXT)
        self.browser_type_picker = self.match_type_picker(create_card)
        live_actions = tk.Frame(self.live_panel, bg=BG)
        live_actions.pack(fill='x')
        self.spectate_button = self.button(live_actions, 'Spectate', self.spectate_selected)
        self.spectate_button.pack(side='left', padx=(0, 8))
        self.stop_watch_button = self.button(live_actions, 'Stop watching', self.stop_watching, False)
        self.stop_watch_button.pack(side='left', padx=(0, 8))
        self.live_refresh_button = self.button(live_actions, 'Refresh', self.refresh_live_matches, False)
        self.live_refresh_button.pack(side='left')
        self.live_join_row = tk.Frame(self.live_panel, bg=BG)
        self.live_join_button = self.button(self.live_join_row, 'Join match', self.join_live_selected)
        self.live_join_button.pack(side='left', padx=(0, 8))
        self.live_join_tip = None
        self.live_join_button.bind('<Enter>', self.show_live_join_tip)
        self.live_join_button.bind('<Leave>', self.hide_live_join_tip)
        self.live_join_row.bind('<Unmap>', self.hide_live_join_tip)
        self.live_team = ttk.Combobox(self.live_join_row, state='disabled', width=26)
        self.live_team.pack(side='left')
        self.live_team.set('Auto Balance')
        self.live_join_reason = tk.StringVar()
        tk.Label(self.live_join_row, textvariable=self.live_join_reason, bg=BG, fg=MUTED,
                 anchor='w', wraplength=260, justify='left').pack(side='left', padx=8)
        self.live_status_label = tk.Label(self.live_panel, textvariable=self.live_status, bg=BG, fg=MUTED, font=('Segoe UI',10),
                 anchor='w', justify='left', wraplength=500)
        self.live_status_label.pack(fill='x', pady=(6, 12))
        tables = tk.Frame(self.live_panel, bg=BG)
        tables.pack(fill='both', expand=True)
        tables.columnconfigure(0, weight=1)
        tables.rowconfigure(0, weight=2)
        tables.rowconfigure(1, weight=1)
        live_card = tk.Frame(tables, bg=PANEL, padx=18, pady=12)
        live_card.grid(row=0, column=0, sticky='nsew')
        self.live_list=ttk.Treeview(live_card,columns=('match','map','players','spectators'),show='headings',height=4,selectmode='browse',style='Live.Treeview')
        for key,title,width in (('match','Match',90),('map','Map',220),('players','Assigned players',115),('spectators','Spectator seats',115)):
            self.live_list.heading(key,text=title);self.live_list.column(key,width=width,minwidth=70,stretch=True)
        live_scroll=ttk.Scrollbar(live_card,orient='vertical',command=self.live_list.yview)
        self.live_list.configure(yscrollcommand=live_scroll.set)
        live_scroll.pack(side='right',fill='y');self.live_list.pack(side='left',fill='both',expand=True)
        self.live_selection = None
        self.live_list.bind('<<TreeviewSelect>>',self.select_live_match)
        roster_panel = tk.Frame(tables,bg=PANEL,padx=18,pady=9)
        roster_panel.grid(row=1, column=0, sticky='nsew', pady=(8, 0))
        self.live_roster_status = tk.StringVar(value='Select a match to see its assigned players.')
        tk.Label(roster_panel,textvariable=self.live_roster_status,bg=PANEL,fg=MUTED,anchor='w').pack(fill='x')
        self.live_roster_table = ttk.Treeview(roster_panel,columns=('blue','red'),show='headings',
                                             height=2,style='Live.Treeview')
        for team in ('blue','red'):
            self.live_roster_table.heading(team,text=TEAM_NAMES[team])
            self.live_roster_table.column(team,width=160,minwidth=80)
        roster_scroll=ttk.Scrollbar(roster_panel,orient='vertical',command=self.live_roster_table.yview)
        self.live_roster_table.configure(yscrollcommand=roster_scroll.set)
        roster_scroll.pack(side='right',fill='y')
        self.live_roster_table.pack(side='left',fill='x',expand=True)
        if self.map_sync is not None:
            self.build_maps_panel()
        self.render_live_controls()
        self.render(None)
        self.run_async(self.lobby.capabilities, self.set_capabilities)
        self.refresh_steam_name()
        self.poll_handle=root.after(150,self.poll)
        self.refresh_handle=root.after(2000,self.refresh)
        self.live_refresh_handle=root.after(3000,self.live_tick)

    def show_lobby_controls(self, in_room):
        if self.lobby_layout == in_room:
            return
        self.lobby_layout = in_room
        if self.retail_import_row is not None:
            if in_room:
                self.retail_import_row.grid_remove()
            else:
                self.retail_import_row.grid()
        self.hero.configure(height=56 if in_room else 180)
        self.hero.pack_configure(expand=not in_room)
        if in_room:
            self.entry_map.grid_remove()
            self.entry_map_label.grid_remove()
            self.room_actions.pack(side='bottom', fill='x', pady=(14, 0))
            self.room_card.pack(fill='both', expand=True, pady=(14, 0))
        else:
            self.room_card.pack_forget()
            self.room_actions.pack_forget()
            self.entry_map_label.grid(row=0, column=2, sticky='w', padx=(12, 0))
            self.entry_map.grid(row=1, column=2, sticky='ew', padx=(12, 0), pady=(4, 8))

    def label(self,parent,text,size=11,bold=False,color=TEXT,bg=BG):
        return tk.Label(parent,text=text,bg=bg,fg=color,font=('Segoe UI',size,'bold' if bold else 'normal'),anchor='w')

    def button(self,parent,text,command,primary=True):
        sidebar = parent is getattr(self, 'sidebar', None)
        return tk.Button(parent,text=text,command=command,bg=ACCENT if primary else '#263e52',fg=BG if primary else TEXT,
                         activebackground='#6ff0d4',relief='flat',padx=14 if sidebar else 10,
                         anchor='w' if sidebar else 'center',pady=7,font=('Segoe UI',10,'bold'))

    @property
    def controls_busy(self):
        return (self.busy and not self.background_busy) or self.queued_action is not None

    def run_async(self, work, success, *, background=False):
        if self.closing:
            return False
        if self.busy:
            if self.background_busy and not background and self.queued_action is None:
                self.queued_action = (work, success)
                self.render(self.room)
                return True
            return False
        self.busy = True
        self.background_busy = background
        if not background:
            self.render(self.room)
        def worker():
            try: self.messages.put((success,work(),None))
            except Exception as exc: self.messages.put((success,None,exc))
        threading.Thread(target=worker,daemon=True).start()
        return True

    def reset_copy_feedback(self):
        if self.copy_reset_handle is not None:
            self.root.after_cancel(self.copy_reset_handle)
            self.copy_reset_handle = None
        self.copy_code_button.configure(text='Copy lobby code')

    def copy_lobby_code(self):
        if self.room is None or self.closing:
            return
        self.reset_copy_feedback()
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.room['code'])
        except tk.TclError:
            self.status.set('Could not copy the lobby code. Please try again.')
            return
        self.copy_code_button.configure(text='Copied!')
        self.copy_reset_handle = self.root.after(2500,self.reset_copy_feedback)

    def watch_notice(self, value):
        key = str(value)

        def changed(*_args):
            handle = self.notice_timers.pop(key, None)
            if handle is not None:
                self.root.after_cancel(handle)
            if value.get() and not self.closing:
                self.notice_timers[key] = self.root.after(NOTICE_MS, expire)

        def expire():
            self.notice_timers.pop(key, None)
            busy = self.controls_busy and value is self.status
            if (value is getattr(self, 'map_status', None)
                    and getattr(self.map_sync, 'notice_active', False) is True):
                busy = True
            if busy:
                self.notice_timers[key] = self.root.after(1000, expire)
            else:
                value.set('')

        value.trace_add('write', changed)

    def poll(self):
        self.poll_handle=None
        if self.closing: return
        try:
            name, error, retry = self.steam_messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.finish_steam_lookup(name, error, retry=retry)
        if self.map_sync is not None:
            target = getattr(self.map_sync, 'notice_target', None)
            current = not isinstance(target, tuple) or target == self.lobby_map_target
            notice = self.map_sync.status if current else ''
            progress = self.map_sync.progress if current else None
            if (target, notice) != self.last_map_notice or progress is not None:
                self.last_map_notice = (target, notice)
                self.map_status.set(notice)
            if progress is None:
                self.map_progress.pack_forget()
            else:
                self.map_progress.configure(value=progress[0], maximum=progress[1])
                if not self.map_progress.winfo_manager():
                    self.map_progress.pack(side='bottom', fill='x', padx=26, pady=(0, 5))
        try:
            while True:
                self.access_messages.get_nowait()()
        except queue.Empty:
            pass
        completed = False
        try:
            while True:
                success,value,error = self.messages.get_nowait()
                self.busy = False
                self.background_busy = False
                completed = True
                if error:
                    message = str(error)
                    if self.map_inflight is not None:
                        if self.pending_map == self.map_inflight:
                            if isinstance(error, CommunityConnectionError):
                                self.map_retry_count += 1
                                self.map_retry_at = (time.monotonic() + self.map_retry_count
                                                     if self.map_retry_count < 3 else float('inf'))
                                message = ('Connection interrupted. Checking your map selection again…'
                                           if self.map_retry_count < 3 else
                                           'Map selection is unconfirmed. Choose the map again to retry.')
                            else:
                                self.pending_map = None
                        self.map_inflight = None
                    if isinstance(error, CommunityError) and error.code in ('lobby_missing', 'session_invalid'):
                        self.render(None)
                    self.status.set(message)
                    if self.current_panel=='live':self.live_status.set(str(error))
                    if (isinstance(error,CommunityError) and error.code in ('spectator_session_invalid','spectator_unavailable')
                            and self.watch_id is not None):
                        self.stop_watching()
                else: success(value)
        except queue.Empty:
            pass
        if self.queued_action is not None and not self.busy:
            work, success = self.queued_action
            self.queued_action = None
            self.run_async(work, success)
        self.flush_map_selection()
        if completed:
            self.render(self.room)
        if self.game:
            try:
                state = self.game.snapshot()
                previous_status=self.game_status
                self.game_status=state['status']
                if self.stop_restarted_client(state):
                    self.game_status = 'stopping'
                    state = dict(state, status='stopping', progress='Closing the previous match…')
                show_notice = not self.ignore_departed_game_notices or state.get('role') in ('spectator', 'public')
                if show_notice and state['status'] in ('starting','playing','stopping'):
                    self.status.set(state.get('progress') or {'starting':'Opening game…','playing':'Game connected.','stopping':'Closing game…'}[state['status']])
                    if self.watch_id is not None:
                        self.live_status.set(state.get('progress') or {'starting':'Opening spectator view…','playing':'Watching match.','stopping':'Closing spectator view…'}[state['status']])
                elif show_notice and state['error'] and state['error'] != self.last_game_error:
                    message = state['error']
                    if self.room and self.room.get('phase') == 'ready' and state.get('role', 'player') == 'player':
                        message += ' Select Join game to retry.'
                    self.shown_game_error = message
                    self.status.set(message)
                elif show_notice and previous_status != self.game_status and state.get('progress'):
                    self.status.set(state['progress'])
                self.last_game_error = state['error']
                preparation=state.get('preparation')
                if show_notice and isinstance(preparation,dict):
                    error = preparation.get('error')
                    if not error or error != self.last_preparation_error:
                        self.preparation.set(error or preparation.get('progress') or '')
                    self.last_preparation_error = error
            except Exception as exc: self.status.set(str(exc))
        self.maybe_auto_join()
        self.render_live_controls()
        if self.current_panel == 'maps':
            self.refresh_map_states()
            self.render_map_controls()
        if not self.closing: self.poll_handle=self.root.after(150,self.poll)

    def set_capabilities(self, caps):
        self.caps = caps
        self.capabilities_loaded = True
        if self.map_sync is not None:
            self.map_sync.start(caps.get('mapFileSync'), session_version=caps.get('mapSessionSync'))
            if self.map_sync.session_enabled and self.maps_panel is not None:
                if self.map_index_rows is None and caps.get('maps'):
                    self.render_map_rows([
                        dict(row, state='Checking…', removable=False) for row in caps['maps']
                    ])
                self.refresh_maps()
        self.status.set('Community service connected.')
        self.render(self.room)
        self.render_live_controls()
        if self.room is None and caps.get('lobbyResumeEnabled') is True:
            self.run_async(self.lobby.resume, self.render)
        elif self.current_panel=='live':
            self.refresh_live_matches()
        elif self.current_panel == 'maps':
            self.refresh_maps()

    def choose_map(self):
        if self.room is None:
            return
        selected=self.map_name.get()
        matches=[item['id'] for item in self.map_options if item['label']==selected]
        if len(matches)!=1:
            self.status.set('Choose an available map.');return
        if self.room is None or self.room['phase'] != 'setup':
            return
        self.pending_map = (self.room['code'], matches[0])
        self.map_retry_count = 0
        self.map_retry_at = 0
        self.clear_match_messages()
        self.status.set('Applying map selection…')
        self.render(self.room)
        self.flush_map_selection()

    def flush_map_selection(self):
        if self.busy or self.closing or self.pending_map is None or time.monotonic() < self.map_retry_at:
            return
        selected = self.pending_map
        if self.room is None or self.room['code'] != selected[0] or self.room['phase'] != 'setup':
            self.pending_map = None
            return
        self.map_inflight = selected
        reconciling = self.map_retry_count > 0
        def apply():
            # A lost reply does not mean the POST failed. Read back first;
            # resend only this idempotent map choice if it was not applied.
            room = self.lobby.action('state') if reconciling else None
            if room is None or room.get('map') != selected[1]:
                room = self.lobby.action('map', map=selected[1])
            if room.get('map') != selected[1]:
                raise CommunityError('The server did not confirm the selected map.')
            return room
        def applied(room):
            self.map_inflight = None
            if self.pending_map == selected:
                self.pending_map = None
                self.map_retry_count = 0
                self.map_retry_at = 0
                self.status.set('Map selected: ' + next(item['label'] for item in self.map_options if item['id'] == selected[1]))
            self.render(room)
        self.run_async(apply, applied)

    def refresh_steam_name(self, *, retry=False):
        loader = self.steam_name_loader
        if not loader or self.closing or self.warrior_name or self.steam_lookup_running:
            return
        if not retry and time.monotonic() < self.steam_lookup_at:
            return
        self.steam_lookup_running = True
        self.steam_lookup_at = time.monotonic() + 60
        results = self.steam_messages

        def worker():
            try:
                name = display_name(loader())
            except Exception as exc:
                reason = getattr(exc, 'reason', type(exc).__name__)
                logging.getLogger(__name__).warning('Steam name lookup failed (%s): %s', reason, exc)
                results.put((None, str(exc), retry))
            else:
                results.put((name, None, retry))

        # Keep the short-lived worker alive through close so subprocess.run can reap the probe.
        threading.Thread(target=worker, name='steam-persona', daemon=False).start()

    def finish_steam_lookup(self, name, error, *, retry):
        previous_notice = self.steam_name_notice()
        self.steam_lookup_running = False
        self.steam_lookup_error = error
        if error is None:
            if name != self.steam_name:
                self.steam_name = name
                try:
                    save_local_name(self.steam_name_path, name)
                except OSError as exc:
                    logging.getLogger(__name__).warning('Could not save the Steam name cache: %s', exc)
            if not self.warrior_name:
                self.name.set(name)
                if self.status.get() == previous_notice:
                    self.status.set('Steam name ready.')
            return
        if self.warrior_name:
            return
        if not self.steam_name:
            self.status.set(self.steam_name_notice())
        if not retry:
            self.steam_retry_handle = self.root.after(2500, self.retry_steam_lookup)

    def retry_steam_lookup(self):
        self.steam_retry_handle = None
        self.refresh_steam_name(retry=True)

    def steam_name_notice(self):
        message = self.steam_lookup_error or 'Looking up your Steam name.'
        return message + ' You can set a Warrior Name in Settings.'

    def player_name_for_action(self):
        if not self.steam_name_loader:
            return display_name(self.name.get().strip())
        if self.warrior_name:
            return self.warrior_name
        self.refresh_steam_name()
        if self.steam_name:
            return self.steam_name
        raise SteamIdentityError(self.steam_name_notice())

    def save_warrior_name(self, value):
        name = display_name(value).strip() if value.strip() else ''
        save_local_name(self.warrior_name_path, name)
        self.warrior_name = name
        self.name.set(name or self.steam_name)
        if name and self.status.get() == self.steam_name_notice():
            self.status.set('Warrior Name saved.')
        if self.steam_retry_handle is not None:
            self.root.after_cancel(self.steam_retry_handle)
            self.steam_retry_handle = None
        if not name:
            self.steam_lookup_at = 0
            self.refresh_steam_name()

    def clear_match_messages(self):
        if self.status.get() == self.shown_game_error:
            self.status.set('')
        if self.preparation.get() == self.last_preparation_error:
            self.preparation.set('')

    def render(self, room):
        previous, current = self.room or {}, room or {}
        if ((previous.get('code'), previous.get('map'), previous.get('phase'))
                != (current.get('code'), current.get('map'), current.get('phase'))):
            self.clear_match_messages()
        if previous.get('code') != current.get('code'):
            self.status.set('')
            self.preparation.set('')
            if self.map_sync is not None:
                self.last_map_notice = (getattr(self.map_sync, 'notice_target', None), self.map_sync.status)
                self.map_status.set('')
                self.map_progress.pack_forget()
            if previous.get('code'):
                self.ignore_departed_game_notices = True
            self.reset_copy_feedback()
        self.room = room
        if self.map_sync is not None and self.caps.get('mapSessionSync') == SESSION_VERSION:
            target = None
            if (room and room.get('phase') in ('setup', 'starting', 'ready')
                    and valid_sha(room.get('contentHash')) and valid_sha(room.get('manifestHash'))):
                target = (room['map'], room['contentHash'], room['manifestHash'])
            if target != self.lobby_map_target:
                self.lobby_map_target = target
                self.map_sync.prefetch(target)
        in_room = room is not None
        self.show_lobby_controls(in_room)
        self.copy_code_button.configure(state='normal' if in_room else 'disabled')
        phase = room['phase'] if in_room else None
        leader = in_room and any(p['id']==room['playerId'] and p['leader'] for p in room['players'])
        setup = in_room and phase=='setup'
        if not setup or not leader or self.pending_map is not None and self.pending_map[0] != room['code']:
            self.pending_map = None
        self.allow_spectators.set(room.get('allowSpectators',True) if in_room else True)
        if self.caps.get('spectateEnabled') is True:
            self.spectator_toggle.pack(side='right',padx=(12,0))
            self.spectator_toggle.configure(state='normal' if setup and leader else 'disabled')
        else:self.spectator_toggle.pack_forget()
        for widget in (self.name_entry, self.code_entry, self.paste_code_button, self.create_button,
                       self.lobby_create_button, self.join_button):
            widget.configure(state='disabled' if in_room or self.controls_busy else 'normal')
        if self.steam_name_loader and not in_room and not self.controls_busy:
            self.name_entry.configure(state='readonly', readonlybackground='#20374a')
        self.browser_name.configure(state=('disabled' if in_room or self.controls_busy else
                                           'readonly' if self.steam_name_loader else 'normal'),
                                    readonlybackground='#20374a')
        if self.caps.get('privateLobbyAdmission') is True:
            self.lobby_lock.grid(row=3, column=2, sticky='w', padx=(12, 0), pady=(4, 0))
            self.browser_lock.pack(side='right', before=self.create_button, padx=(0, 6))
            for checkbox in (self.lobby_lock, self.browser_lock):
                checkbox.configure(state='disabled' if in_room or self.controls_busy else 'normal')
        else:
            self.lobby_lock.grid_remove()
            self.browser_lock.pack_forget()
        if self.caps.get('lobbyMatchTypes') is True:
            self.lobby_type_row.grid(row=3, column=1, sticky='w', padx=(12,0), pady=(4,0))
            self.browser_type_picker.pack(side='right', before=self.create_button, padx=(0,8))
            for picker in (self.lobby_type_picker, self.browser_type_picker):
                picker.configure(state='disabled' if in_room or self.controls_busy else 'readonly')
            if self.lobby_match_type.get() != 'Standard':
                self.lobby_lock.configure(state='disabled')
                self.browser_lock.configure(state='disabled')
        else:
            self.lobby_type_row.grid_remove()
            self.browser_type_picker.pack_forget()
        if in_room:
            heading = 'Lobby  ' + room['code']
            match_type = room.get('matchType', 'standard')
            if match_type != 'standard' and match_type in ('competition', 'scrim', 'pug'):
                heading += '  ·  ' + ('PUG' if match_type == 'pug' else match_type.title())
            if room.get('locked'):
                heading += '  ·  Locked'
            self.room_heading.set(heading)
        else:
            self.room_heading.set('Not in a lobby')
        self.phase.set(match_phase_text(room))
        restart = room.get('restart') if in_room else None
        restarting = isinstance(restart, dict) and restart.get('stage') in ('countdown', 'checkpointing', 'draining', 'starting', 'restoring')
        can_restart = (leader and self.caps.get('matchRestartEnabled') is True
                       and phase in ('starting', 'ready', 'stopped', 'ended', 'failed'))
        if can_restart:
            if not self.restart_button.winfo_manager():
                self.restart_button.pack(side='left', before=self.reset_button, padx=(0, 8))
            self.restart_button.configure(state='disabled' if restarting or self.controls_busy else 'normal')
        else:
            self.restart_button.pack_forget()
        available=room.get('availableMaps') if in_room else self.caps.get('maps')
        if available is None: available=options(LEGACY_MAPS)
        try:
            dynamic = self.caps.get('mapFileSync') == CATALOG_VERSION
            if dynamic:
                from community_transport import read_server_map_options
                labels = read_server_map_options(available)
            else:
                labels = read_options(available)
            if in_room and room['map'] not in labels:
                raise ValueError('The selected map is outside the lobby catalog.')
        except ValueError:
            self.map_combo.configure(state='disabled')
            self.start_button.configure(state='disabled')
            self.game_button.configure(state='disabled')
            self.leave_button.configure(state='normal' if in_room and not self.controls_busy else 'disabled')
            self.status.set('Unsupported server map catalog. Update the community client.')
            return
        self.map_options=sorted(available, key=lambda item: item['label'].casefold())
        self.create_map.configure(values=tuple(sorted(labels.values(), key=str.casefold)), height=min(18, len(labels)),
                                  state='readonly' if not in_room and not self.controls_busy
                                  and self.caps.get('mapSessionSync') == SESSION_VERSION else 'disabled')
        self.entry_map.configure(values=self.create_map.cget('values'), state=self.create_map.cget('state'))
        if self.create_map_name.get() not in labels.values():
            self.create_map_name.set(next(iter(labels.values()), ''))
        self.map_combo.configure(values=tuple(item['label'] for item in self.map_options),height=min(18,len(available)),state='readonly' if setup and leader else 'disabled')
        self.map_combo.configure(textvariable=self.map_name if in_room else self.create_map_name)
        if not in_room:
            self.map_combo.configure(state=self.create_map.cget('state'))
        if in_room:
            if self.pending_map and self.pending_map[1] not in labels:
                self.pending_map = None
            self.map_name.set(labels[self.pending_map[1] if self.pending_map else room['map']])
        editable = setup and leader and not self.controls_busy and self.pending_map is None
        self.render_match_rules(room, editable)
        self.render_rosters(room)
        self.render_sides(room, editable)
        for widget in (self.blue_button,self.red_button): widget.configure(state='normal' if setup and not self.controls_busy else 'disabled')
        for widget in (self.move_blue,self.move_red): widget.configure(state='normal' if setup and leader and not self.controls_busy else 'disabled')
        self.start_button.configure(state='normal' if setup and leader and not self.controls_busy and self.pending_map is None and self.caps.get('matchStartEnabled') else 'disabled')
        match = (room.get('match') or {}) if in_room else {}
        join_allowed = not restarting or (restart.get('stage') == 'restoring'
                                          and match.get('id')
                                          and restart.get('replacementMatchId') == match.get('id'))
        self.game_button.configure(state='normal' if in_room and phase=='ready' and match.get('status') != 'starting' and join_allowed and not self.controls_busy and self.pending_map is None and self.caps.get('gameClientReady') else 'disabled')
        replacement = restart.get('replacementMatchId') if restarting else None
        allocated_replacement = replacement and replacement == match.get('id')
        can_stop = leader and phase in ('starting', 'ready') and (not restarting or allocated_replacement)
        self.stop_button.configure(state='normal' if can_stop else 'disabled')
        self.reset_button.configure(state='normal' if leader and not restarting and phase in ('stopped','ended','failed') else 'disabled')
        self.leave_button.configure(state='normal' if in_room and not self.controls_busy else 'disabled')
        # Preparation has no match endpoint or player profile. Start it as soon
        # as the service confirms support, while the player is choosing a lobby.
        if self.capabilities_loaded and self.caps.get('gameClientReady') and self.map_sync is None:
            try:
                if not self.game:self.game=self.game_factory(self.lobby)
                prepare=getattr(self.game,'prepare',None)
                if prepare:prepare()
            except Exception as exc:
                self.preparation.set('Game preparation: '+str(exc))

    def match_type_picker(self, parent):
        picker = ttk.Combobox(parent, textvariable=self.lobby_match_type,
                              values=('Standard', 'Competition', 'Scrim', 'PUG'), width=13, state='disabled')
        picker.bind('<<ComboboxSelected>>', self.change_lobby_match_type)
        return picker

    def change_lobby_match_type(self, _event):
        self.lock_lobby.set(self.lobby_match_type.get() != 'Standard')
        self.render(self.room)

    def create(self):
        def created(room):
            self.render(room)
            self.show_panel('lobbies')
        selected = next((item['id'] for item in self.map_options if item['label'] == self.create_map_name.get()), None)
        options = {'map_id': selected} if selected and self.caps.get('mapSessionSync') == SESSION_VERSION else {}
        if self.caps.get('privateLobbyAdmission') is True:
            options['locked'] = self.lock_lobby.get()
        if self.caps.get('lobbyMatchTypes') is True:
            options['match_type'] = self.lobby_match_type.get().lower()
        self.enter_lobby(lambda name: self.lobby.create(name, **options), success=created)

    def paste_lobby_code(self, _event=None):
        if self.code_entry.cget('state') == 'disabled':
            return 'break'
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            value = ''
        code = normalize_lobby_code(value)
        if code is None:
            self.status.set('Clipboard does not contain a valid lobby code.')
        else:
            self.code.set(code)
            self.code_entry.icursor(tk.END)
        return 'break'

    def open_lobby_code_menu(self, event):
        if self.code_entry.cget('state') != 'disabled':
            try:
                self.code_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.code_menu.grab_release()
        return 'break'

    def join(self):
        code = normalize_lobby_code(self.code.get())
        if code is None:
            self.status.set('Enter a valid six-character lobby code.')
            return
        self.code.set(code)
        self.enter_lobby(lambda name: self.lobby.join(code,name))

    def enter_lobby(self, operation, success=None):
        try:
            name = self.player_name_for_action()
        except (ValueError, SteamIdentityError) as exc:
            self.status.set(str(exc))
            return
        self.run_async(lambda: operation(name), success or self.render)
    def call_action(self,operation,**data):
        if operation == 'leave':
            return self.exit_lobby()
        if operation == 'start' and self.pending_map is not None:
            self.status.set('Wait for the selected map to be confirmed.')
            return
        def work():
            return self.lobby.action(operation,**data)
        messages = {
            'start': 'Starting match…', 'stop': 'Stopping match…',
            'reset': 'Setting up the lobby…',
            'restart': 'Scheduling the match restart…',
        }
        if operation not in messages:
            self.run_async(work, self.render)
            return

        def completed(room):
            self.render(room)
            self.status.set(match_phase_text(room))

        if self.run_async(work, completed):
            self.clear_match_messages()
            self.status.set(messages[operation])

    def exit_lobby(self):
        if self.room is None or self.controls_busy or self.closing:
            return
        code = self.room['code']
        game = self.game

        def leave():
            cleanup_error = None
            if game is not None:
                try:
                    state = game.snapshot()
                    if (state.get('role', 'player') == 'player'
                            and state['status'] in ('starting', 'playing', 'stopping')):
                        game.stop()
                except (OSError, CommunityError) as exc:
                    cleanup_error = str(exc)
            try:
                self.lobby.action('leave')
                confirmed = True
            except (OSError, CommunityError) as exc:
                confirmed = getattr(exc, 'code', None) in ('lobby_missing', 'session_invalid')
            finally:
                # The wire membership is best effort. Clear only this client
                # session, under the same lock as a request that could update it.
                with self.lobby.lock:
                    if self.lobby.code == code:
                        self.lobby.code = self.lobby.token = self.lobby.player_id = None
            message = 'Left lobby.' if confirmed else 'Lobby closed on this device. Server confirmation is unavailable.'
            return f'{message} Game cleanup: {cleanup_error}' if cleanup_error else message

        if self.run_async(leave, self.status.set):
            self.render(None)
            self.show_panel('live')
            self.status.set('Closing lobby on this device…')

    def move(self,team):
        player = self.selected_player()
        if player is None: self.status.set('Select a player first.');return
        self.call_action('team',team=team,playerId=player)

    def select_roster(self, selected):
        if selected.curselection():
            for box in self.rosters.values():
                if box is not selected:
                    box.selection_clear(0, tk.END)

    def selected_player(self):
        for team, box in self.rosters.items():
            indices = box.curselection()
            if indices and indices[0] < len(self.roster_players[team]):
                return self.roster_players[team][indices[0]]['id']
        return None

    def render_rosters(self, room):
        selected = self.selected_player()
        self.players = room['players'] if room else []
        for team, box in self.rosters.items():
            offset = box.yview()[0]
            players = [p for p in self.players if (p['team'] or None) == team]
            self.roster_players[team] = players
            box.delete(0, tk.END)
            for index, player in enumerate(players):
                box.insert(tk.END, player['name'] + ('  • leader' if player['leader'] else '')
                           + ('  • you' if player['id'] == room['playerId'] else ''))
                if player['id'] == selected:
                    box.selection_set(index)
                    box.activate(index)
            if room:
                box.yview_moveto(offset)

    def render_sides(self, room, editable):
        side = room.get('blueSide') if room else None
        if side not in ('A', 'B'):
            self.side_row.pack_forget()
            return
        if not self.side_row.winfo_manager():
            self.side_row.pack(fill='x', before=self.roster_frame, pady=(6, 0))
        self.blue_side.set('Side ' + side)
        self.red_side.set('Diamond Sword starts on Side A · In-game colors swap' if side == 'B'
                          else 'Diamond Sword starts on Side B')
        self.side_combo.configure(state='readonly' if editable else 'disabled')

    def choose_side(self, _event=None):
        if self.side_combo.instate(('readonly',)):
            value = self.blue_side.get()
            if value in ('Side A', 'Side B'):
                self.call_action('rules', blueSide=value[-1])

    def restart_match(self):
        if self.room is None or self.restart_button.cget('state') != 'normal':
            return
        match = self.room.get('match')
        if not isinstance(match, dict) or not match.get('id'):
            return
        mode = None
        if (self.caps.get('matchRestartKeepScore') is True
                and (match.get('loading') or {}).get('state') == 'playing'):
            keep_score = messagebox.askyesnocancel(
                'Restart match', 'Keep the score and remaining time?\n\nChoose No to start a fresh round.',
                parent=self.root,
            )
            if keep_score is None:
                return
            mode = 'keep_score' if keep_score else 'full'
        reason = simpledialog.askstring(
            'Restart match', ('The same map and teams will restart with the saved score and clock.'
                              if mode == 'keep_score' else 'The same map and teams will start a fresh round.')
            + '\n\nReason for the restart',
            parent=self.root,
        )
        if reason is not None:
            reason = reason.strip()
            if not 1 <= len(reason) <= 120 or not reason.isprintable():
                self.status.set('Enter a printable restart reason of 1–120 characters.')
                return
            details = {'mode': mode} if mode is not None else {}
            self.call_action('restart', matchId=match['id'], reason=reason, **details)

    def stop_restarted_client(self, state):
        restart = self.room.get('restart') if self.room else None
        if (isinstance(restart, dict) and restart.get('stage') in ('draining', 'starting', 'restoring', 'complete')
                and state.get('role') == 'player' and state['status'] in ('starting', 'playing')
                and state.get('matchId') and state['matchId'] == restart.get('matchId')):
            self.game.stop()
            return True
        return False

    def maybe_auto_join(self):
        if (self.busy or self.watch_id is not None or self.game_status not in ('idle', 'stopped', 'finished', 'failed')
                or self.game_button.cget('state') != 'normal'):
            return
        room = self.room
        match = room.get('match') if room else None
        if not isinstance(match, dict) or match.get('status') != 'ready':
            return
        match_id = match.get('id')
        if not match_id or match_id == self.join_attempted_match:
            return
        if any(p['id'] == room['playerId'] and p['team'] in ('blue', 'red') for p in room['players']):
            self.join_game()

    def join_game(self):
        if self.controls_busy or self.closing: return
        if self.room is None or self.pending_map is not None:
            self.status.set('Wait for the selected map to be confirmed.');return
        if self.watch_id is not None:
            self.status.set('Stop watching the current match first.');return
        self.clear_match_messages()
        self.status.set('Checking the selected match…')
        selected_map = self.room['map']
        match = self.room.get('match')
        match_id = match.get('id') if isinstance(match, dict) else None
        def begin():
            if not self.game: self.game = self.game_factory(self.lobby)
            if match_id:
                return self.game.start(expected_map=selected_map, expected_match_id=match_id)
            return self.game.start(expected_map=selected_map)
        if self.run_async(begin,lambda _:self.status.set('Opening game…')):
            self.ignore_departed_game_notices = False
            self.join_attempted_match = match_id

    def toggle_spectators(self):
        if self.room is not None and self.caps.get('spectateEnabled')is True:
            self.call_action('spectators',allow=self.allow_spectators.get())

    def render_match_rules(self, room, editable):
        if self.caps.get('matchRulesEnabled') is not True:
            self.rules_row.pack_forget()
            return
        if not self.rules_row.winfo_manager():
            self.rules_row.pack(fill='x',before=self.roster_frame,pady=(6,0))
        rules = room.get('rules', DEFAULT_LOBBY_RULES) if room else DEFAULT_LOBBY_RULES
        self.flag_indicators.set(rules['flagIndicators'])
        self.fall_damage.set(rules.get('fallDamage') is True)
        if self.caps.get('fallDamageEnabled') is True:
            if not self.fall_toggle.winfo_manager():
                self.fall_toggle.pack(side='left', after=self.flag_toggle)
            self.fall_toggle.configure(state='normal' if editable else 'disabled')
        else:
            self.fall_toggle.pack_forget()
        count = rules['botCount']
        self.allow_bots.set(count > 0)
        if count:
            self.bot_count.set(str(count))
        self.retail_capture_point.set(rules['retailCapturePoint'])
        definition = BY_ID.get(room['map']) if room else None
        for control in (self.flag_toggle, self.bot_toggle):
            control.configure(state='normal' if editable else 'disabled')
        self.bot_spinner.configure(state='readonly' if editable and count else 'disabled')
        self.capture_toggle.configure(state='normal' if editable and definition and definition.native else 'disabled')

    def change_bots(self):
        self.call_action('rules',botCount=int(self.bot_count.get()) if self.allow_bots.get() else 0)

    def show_panel(self,name):
        if self.closing:return
        self.current_panel=name
        self.lobby_panel.pack_forget();self.live_panel.pack_forget()
        if self.maps_panel is not None:
            self.maps_panel.pack_forget()
        panel = self.maps_panel if name == 'maps' else self.live_panel if name == 'live' else self.lobby_panel
        panel.pack(side='left',fill='both',expand=True,padx=32,pady=28)
        self.render_live_controls()
        if name=='live':self.refresh_live_matches()
        if name=='maps':self.refresh_maps()

    def build_maps_panel(self):
        self.maps_panel = panel = tk.Frame(self.root, bg=BG)
        self.label(panel, 'Maps', 27, True).pack(anchor='w')
        table = tk.Frame(panel, bg=PANEL, padx=12, pady=12)
        table.pack(fill='both', expand=True, pady=(14, 12))
        columns = (('name', 'Map', 165), ('game', 'Game', 62), ('size', 'Size', 72),
                   ('version', 'Version', 78), ('status', 'Local status', 112))
        self.map_sort = None
        self.map_headings = {key:title for key,title,_ in columns}
        self.maps_table = ttk.Treeview(table, columns=tuple(self.map_headings),
                                       show='headings', style='Live.Treeview', selectmode='extended')
        for key, title, width in columns:
            self.maps_table.heading(key, text=title, command=lambda column=key: self.sort_maps(column))
            self.maps_table.column(key, width=width, minwidth=width-12)
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.maps_table.yview)
        self.maps_table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.maps_table.pack(side='left', fill='both', expand=True)
        self.maps_table.bind('<<TreeviewSelect>>', lambda _event: self.render_map_controls())
        self.maps_table.bind('<Control-a>', self.select_all_maps)
        self.maps_table.bind('<Control-A>', self.select_all_maps)
        self.map_rows = {}
        self.map_queue = deque()
        self.map_active = None
        self.map_queue_total = self.map_queue_done = self.map_queue_cancelled = 0
        self.map_queue_errors = []
        self.map_index_rows = None
        self.map_index_busy = False
        self.map_state_busy = False
        self.map_state_version = None
        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(fill='x')
        self.map_download = self.button(buttons, 'Download selected', self.queue_selected_maps)
        self.map_download.pack(side='left', padx=(0, 8))
        self.map_remove = self.button(buttons, 'Remove download', self.remove_map_download, False)
        self.map_remove.pack(side='left', padx=(0, 8))
        self.map_refresh = self.button(buttons, 'Refresh', self.refresh_maps, False)
        self.map_refresh.pack(side='left')
        queue_controls = tk.Frame(panel, bg=BG)
        queue_controls.pack(fill='x', pady=(5, 0))
        self.map_cancel_selected = self.button(queue_controls, 'Cancel selected', self.cancel_selected_maps, False)
        self.map_cancel_all = self.button(queue_controls, 'Cancel all', self.cancel_all_maps, False)
        self.map_cancel_selected.pack(side='left', padx=(0,8))
        self.map_cancel_all.pack(side='left')
        self.map_selection_notice = tk.StringVar()
        self.map_queue_notice = tk.StringVar()
        for variable in (self.map_selection_notice, self.map_queue_notice):
            tk.Label(panel, textvariable=variable, bg=BG, fg=MUTED, wraplength=530,
                     anchor='w', justify='left').pack(fill='x', pady=(5, 0))
        self.maps_notice = tk.StringVar()
        tk.Label(panel, textvariable=self.maps_notice, bg=BG, fg=MUTED, wraplength=530,
                 anchor='w', justify='left').pack(fill='x', pady=(10, 0))

    def select_all_maps(self, _event=None):
        self.maps_table.selection_set(self.maps_table.get_children())
        return 'break'

    def sort_maps(self, column):
        previous, descending = self.map_sort or (None, False)
        self.map_sort = column, not descending if previous == column else False
        self.order_maps()

    def order_maps(self):
        column, descending = self.map_sort or ('name', False)
        fields = {'name':'label', 'game':'gameTag', 'size':'bytes', 'version':'manifestHash', 'status':'state'}
        field = fields[column]
        def key(identity):
            row = self.map_rows[identity]
            return row.get(field, -1) if column == 'size' else row.get(field, '').casefold()
        for index, identity in enumerate(sorted(self.maps_table.get_children(), key=key, reverse=descending)):
            self.maps_table.move(identity, '', index)
        arrow = ' \u25bc' if descending else ' \u25b2'
        for name, label in self.map_headings.items():
            self.maps_table.heading(name, text=label + arrow if self.map_sort and name == column else label)

    def queued_map_ids(self):
        identities = {row['id'] for row in self.map_queue}
        if self.map_active is not None:
            identities.add(self.map_active[0]['id'])
        return identities

    def render_map_controls(self):
        selected = self.maps_table.selection()
        rows = [self.map_rows[identity] for identity in selected if identity in self.map_rows]
        queued = self.queued_map_ids()
        downloadable = [row for row in rows if row['state'] in ('Not downloaded', 'Update available')]
        new = [row for row in downloadable if row['id'] not in queued]
        total = sum(row['bytes'] for row in downloadable)
        self.map_selection_notice.set(f'{len(rows)} selected · up to {total/1024**2:,.1f} MiB to download'
                                      if rows else '')
        enabled = self.map_sync.session_enabled
        idle_game = self.game_status in ('idle', 'stopped', 'finished', 'failed')
        removable = (len(rows) == 1 and rows[0]['removable'] and rows[0]['id'] not in queued)
        self.map_refresh.configure(state='normal' if enabled and not self.map_index_busy else 'disabled')
        self.map_download.configure(state='normal' if enabled and new else 'disabled')
        self.map_remove.configure(state='normal' if enabled and removable and idle_game
                                  and not self.controls_busy else 'disabled')
        self.map_cancel_selected.configure(state='normal' if queued.intersection(selected) else 'disabled')
        self.map_cancel_all.configure(state='normal' if queued else 'disabled')
        self.render_map_queue_progress()

    def render_map_queue_progress(self):
        if self.map_active is not None:
            row, cancelled = self.map_active
            progress = self.map_sync.progress if self.map_sync.notice_target == row['id'] else None
            detail = f' · {progress[0]:,}/{progress[1]:,} files' if progress and progress[1] else ''
            action = 'Cancelling' if cancelled.is_set() else 'Downloading'
            self.map_queue_notice.set(f'{action} {row["label"]}{detail} · '
                                      f'{self.map_queue_done}/{self.map_queue_total} maps processed')
        elif self.map_queue_total:
            failed = len(self.map_queue_errors)
            complete = self.map_queue_done - self.map_queue_cancelled - failed
            summary = f'{complete} downloaded · {self.map_queue_cancelled} cancelled · {failed} failed'
            if failed:
                summary += '\n' + self.map_queue_errors[-1]
            self.map_queue_notice.set(summary)

    def render_map_rows(self, rows):
        updated = {row['id']: row for row in rows}
        if updated == self.map_rows:
            return
        selected = self.maps_table.selection()
        focus = self.maps_table.focus()
        scroll = self.maps_table.yview()[0]
        # Retain prior row order for stable sorting and preserve selection on live refresh.
        order = list(dict.fromkeys((*self.maps_table.get_children(), *updated)))
        self.maps_table.delete(*self.maps_table.get_children())
        self.map_rows = updated
        for identity in order:
            row = updated.get(identity)
            if row is None:
                continue
            size = f"{row['bytes']/1024**2:,.1f} MiB" if 'bytes' in row else ''
            self.maps_table.insert('', 'end', iid=identity,
                                   values=(row['label'], row.get('gameTag', ''), size,
                                           row.get('manifestHash', '')[:8], row['state']))
        self.order_maps()
        self.maps_table.selection_set(tuple(identity for identity in selected if identity in updated))
        if focus in updated:
            self.maps_table.focus(focus)
        self.maps_table.yview_moveto(scroll)
        self.render_map_controls()

    def fetch_map_rows(self, work, finished):
        results = self.access_messages

        def worker():
            try:
                rows, error = work(), None
            except (CommunityError, OSError, ValueError, TypeError, RecursionError) as exc:
                rows, error = None, str(exc)
            results.put(lambda: finished(rows, error))

        threading.Thread(target=worker, name='maps-catalog', daemon=True).start()

    def refresh_maps(self):
        if not self.capabilities_loaded or self.map_index_busy:
            return
        if not self.map_sync.session_enabled:
            self.maps_notice.set('Per-map downloads are unavailable on this server.')
            self.render_map_controls()
            return
        self.map_index_busy = True
        if not self.map_rows:
            self.maps_notice.set('Checking map catalog…')

        def loaded(rows, error):
            self.map_index_busy = False
            if error is not None:
                self.maps_notice.set('Map list may be out of date. ' + error if self.map_rows else error)
            else:
                self.maps_notice.set('')
                if rows is not self.map_index_rows:
                    self.map_index_rows = rows
                    self.map_state_version = None
                    self.render_map_rows([
                        dict(row, state=previous['state'], removable=previous['removable'])
                        if (previous := self.map_rows.get(row['id'])) is not None
                        and previous.get('manifestHash') == row['manifestHash']
                        else dict(row, state='Checking…', removable=False) for row in rows
                    ])
                self.refresh_map_states()
            self.render_map_controls()

        self.fetch_map_rows(self.map_sync.refresh_map_index, loaded)
        self.render_map_controls()

    def refresh_map_states(self):
        index = self.map_index_rows
        version = self.map_sync.local_version
        if index is None or self.map_state_busy or self.map_state_version == version:
            return
        self.map_state_busy = True

        def loaded(rows, error):
            self.map_state_busy = False
            if index is not self.map_index_rows or version != self.map_sync.local_version:
                self.refresh_map_states()
                return
            self.map_state_version = version
            if error is not None:
                if not self.maps_notice.get():
                    self.maps_notice.set('Could not check downloaded maps. ' + error)
                return
            self.render_map_rows(rows)

        self.fetch_map_rows(lambda: self.map_sync.local_maps(index), loaded)

    def queue_selected_maps(self):
        if not self.map_sync.session_enabled:
            return
        selected = set(self.maps_table.selection())
        queued = self.queued_map_ids()
        rows = [self.map_rows[identity] for identity in self.maps_table.get_children()
                if identity in selected and identity not in queued
                and self.map_rows[identity]['state'] in ('Not downloaded', 'Update available')]
        if not rows:
            return
        if not queued:
            self.map_queue_total = self.map_queue_done = self.map_queue_cancelled = 0
            self.map_queue_errors.clear()
        self.map_queue.extend(rows)
        self.map_queue_total += len(rows)
        self.download_next_map()
        self.render_map_controls()

    def download_next_map(self):
        if self.closing or self.map_active is not None or not self.map_queue:
            return
        row = self.map_queue.popleft()
        cancelled = threading.Event()
        self.map_active = (row, cancelled)

        def check():
            if cancelled.is_set():
                raise CommunityError('Map download cancelled.')
            return False

        def download():
            return self.map_sync.sync_map(row['id'], row['contentHash'], row['manifestHash'],
                                         obsolete=check, notice_target=row['id'])

        def complete(_, error):
            self.map_active = None
            self.map_queue_done += 1
            if error:
                if cancelled.is_set():
                    self.map_queue_cancelled += 1
                else:
                    self.map_queue_errors.append(f'{row["label"]}: {error}')
            else:
                displayed = self.map_rows.get(row['id'])
                if displayed and row['manifestHash'] == displayed.get('manifestHash'):
                    self.render_map_rows([
                        dict(item, state='Downloaded', removable=True) if item is displayed else item
                        for item in self.map_rows.values()
                    ])
            self.map_state_version = None
            self.refresh_map_states()
            self.download_next_map()
            self.render_map_controls()

        self.fetch_map_rows(download, complete)

    def cancel_selected_maps(self):
        self.cancel_maps(set(self.maps_table.selection()))

    def cancel_all_maps(self):
        self.cancel_maps(self.queued_map_ids())

    def cancel_maps(self, identities):
        before = len(self.map_queue)
        self.map_queue = deque(row for row in self.map_queue if row['id'] not in identities)
        cancelled = before - len(self.map_queue)
        self.map_queue_done += cancelled
        self.map_queue_cancelled += cancelled
        if self.map_active is not None and self.map_active[0]['id'] in identities:
            self.map_active[1].set()
        self.render_map_controls()

    def remove_map_download(self):
        selected = self.maps_table.selection()
        if len(selected) != 1 or self.controls_busy or self.game_status not in ('idle','stopped','finished','failed'):
            return
        identity = selected[0]
        if not self.map_rows[identity]['removable'] or identity in self.queued_map_ids():
            return
        def work():
            try:
                self.map_sync.remove_map(identity)
            except (CommunityError, OSError, ValueError) as exc:
                return str(exc)
            return None

        def complete(error):
            if error:
                self.maps_notice.set(error)
            self.map_state_version = None
            self.refresh_map_states()

        self.run_async(work, complete)

    def offer_retail_import(self, settings_dir, check, apply):
        """Offer the retail import inline without interrupting lobby setup."""
        from player_profile import remember_retail_import_prompt, retail_import_prompt_pending

        if self.retail_import_row is not None or self.closing:
            return
        try:
            if not retail_import_prompt_pending(settings_dir) or check() is None:
                return
        except (OSError, ValueError):
            return
        row = self.retail_import_row = tk.Frame(self.entry_panel, bg=PANEL)
        row.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        if self.lobby_layout:
            row.grid_remove()
        actions = tk.Frame(row, bg=PANEL)
        actions.pack(fill='x')
        notice = tk.StringVar(row)
        message = tk.Label(row, textvariable=notice, bg=PANEL, fg=MUTED, justify='left', anchor='w')
        row.bind('<Configure>', lambda event: message.configure(wraplength=max(1, event.width)))
        message.pack(fill='x')

        def complete(result):
            try:
                remember_retail_import_prompt(settings_dir, 'done')
            except (OSError, ValueError):
                result += ' Starter could not save your import preference.'
            actions.destroy()
            self.retail_import_complete = None
            notice.set(result)

        self.retail_import_complete = complete

        def dismiss():
            try:
                remember_retail_import_prompt(settings_dir, 'dismissed')
            except (OSError, ValueError):
                notice.set('Starter could not save your choice. Try again.')
                return
            self.retail_import_complete = None
            row.destroy()
            self.retail_import_row = None

        def import_settings():
            if self.controls_busy or self.game_status not in ('idle', 'stopped', 'finished', 'failed'):
                notice.set('Close TRIBES 3 and wait for Starter to finish its current action.')
                return
            try:
                result = apply()
            except (OSError, ValueError) as exc:
                notice.set(str(exc))
                return
            complete(result)

        self.button(actions, 'Import retail settings', import_settings).pack(side='left')
        self.button(actions, 'Dismiss', dismiss, False).pack(side='left', padx=(8, 0))

    def offer_windows_retail_import(self, workspace):
        from player_profile import import_retail_settings, user_profile_root, windows_retail_import_offer

        try:
            root = user_profile_root()
        except (OSError, ValueError):
            return

        def apply():
            changed = import_retail_settings(root=root, workspaces=(workspace,), first_launch=True)
            return ('Retail settings imported. They apply the next time you open the game.'
                    if changed else 'Your community settings already match the saved retail settings.')

        self.offer_retail_import(root, lambda: windows_retail_import_offer(root, (workspace,)), apply)

    def show_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        from player_profile import ProfileError, import_retail_settings

        window = tk.Toplevel(self.root, bg=BG, padx=24, pady=20)
        self.settings_window = window
        window.title('Settings')
        window.transient(self.root)
        window.resizable(False, False)
        if self.steam_name_loader:
            self.label(window, 'Warrior Name', 16, True).pack(anchor='w')
            self.label(window, 'Leave blank to use your Steam name.', color=MUTED).pack(anchor='w', pady=(4, 8))
            value = tk.StringVar(window, value=self.warrior_name)
            entry = tk.Entry(window, textvariable=value, font=('Segoe UI', 11), bg='#20374a',
                             fg=TEXT, insertbackground=TEXT, relief='flat')
            entry.pack(fill='x', ipady=6)
            notice = tk.StringVar(window)

            def save_name():
                try:
                    self.save_warrior_name(value.get())
                except (OSError, ValueError) as exc:
                    notice.set(str(exc))
                    return
                value.set(self.warrior_name)
                notice.set('Name saved for your next join.' if self.warrior_name else 'Using your Steam name.')

            entry.bind('<Return>', lambda _event: save_name())
            self.button(window, 'Save name', save_name, False).pack(anchor='w', pady=(8, 0))
            tk.Label(window, textvariable=notice, bg=BG, fg=MUTED, font=('Segoe UI', 10),
                     justify='left', wraplength=420, anchor='w').pack(fill='x', pady=(3, 10))
            tk.Frame(window, bg=PANEL, height=1).pack(fill='x', pady=(0, 14))
        self.label(window, 'Game settings', 16, True).pack(anchor='w')
        description = self.label(
            window, 'Copy your retail key bindings, weapon inheritance, and other game settings. '
            'Starter backs up any community settings files it replaces.', 11, color=MUTED)
        description.configure(wraplength=420, justify='left')
        description.pack(anchor='w', pady=(8, 14))
        status = tk.StringVar(window, value='Close TRIBES 3 before importing.')

        def import_settings():
            if self.controls_busy or self.game_status not in ('idle', 'stopped', 'finished', 'failed'):
                status.set('Close TRIBES 3 and wait for Starter to finish its current action.')
                return
            try:
                changed = import_retail_settings()
            except (OSError, ProfileError) as exc:
                status.set(str(exc))
                return
            result = ('Retail settings imported. They apply the next time you open the game.'
                      if changed else 'Your community settings already match the saved retail settings.')
            status.set(result)
            if self.retail_import_complete is not None:
                self.retail_import_complete(result)

        self.button(window, 'Import settings from retail', import_settings).pack(anchor='w')
        tk.Label(window, textvariable=status, bg=BG, fg=MUTED, font=('Segoe UI', 10),
                 justify='left', wraplength=420, anchor='w').pack(fill='x', pady=(12, 0))
        self.button(window, 'About this launcher', self.show_connection_info, False).pack(
            anchor='w', pady=(12, 0))
        window.bind('<Escape>', lambda _event: window.destroy())

    def live_browser_supported(self):
        return self.caps.get('spectateEnabled') is True or self.caps.get('privateLobbyAdmission') is True

    def render_live_controls(self):
        supported=self.caps.get('spectateEnabled')is True
        player_admission = self.caps.get('privateLobbyAdmission') is True
        selected=self.live_list.selection()
        target=self.live_targets.get(selected[0])if selected else None
        active=self.game_status not in ('idle','stopped','finished','failed')
        can_watch=supported and target is not None and target.get('canSpectate')is True and not active and self.watch_id is None
        self.spectate_button.configure(state='normal'if can_watch and not self.controls_busy else'disabled')
        self.stop_watch_button.configure(state='normal'if self.watch_id is not None and not self.controls_busy else'disabled')
        self.live_refresh_button.configure(state='normal' if self.live_browser_supported() and not self.controls_busy else 'disabled')
        if not self.live_browser_supported() and self.capabilities_loaded:
            self.live_status.set('Live matches are unavailable on this server version.')
        if not player_admission:
            self.live_join_row.pack_forget()
            return
        if not self.live_join_row.winfo_manager():
            self.live_join_row.pack(before=self.live_status_label, fill='x', pady=(8, 0))
        returning = bool(target and target.get('rejoin'))
        ready = bool(target and target.get('canJoin') and self.caps.get('gameClientReady')
                     and not (active or self.watch_id or self.controls_busy or self.closing))
        self.live_join_button.configure(text='Rejoin' if returning else 'Join match', state='normal' if ready else 'disabled')
        self.live_join_reason.set(target.get('joinReason', '') if target else '')
        if not self.live_join_reason.get():
            self.hide_live_join_tip()
        counts = target.get('teamCounts', {}) if target else {}
        values = ('Auto Balance', *(f'{TEAM_NAMES[side]} ({counts[side]})' if side in counts else TEAM_NAMES[side]
                                    for side in ('blue', 'red')))
        if tuple(self.live_team['values']) != values:
            selected_team = self.live_team.current()
            self.live_team.configure(values=values)
            self.live_team.current(max(0, selected_team))
        self.live_team.configure(state='readonly' if ready and not returning else 'disabled')

    def select_live_match(self,event):
        self.render_live_controls()
        self.render_live_roster()
        selected = self.live_list.selection()
        match_id = selected[0] if selected else None
        if match_id != self.live_selection:
            self.live_selection = match_id
            if match_id:
                self.refresh_live_matches(background=True)

    def render_live_roster(self):
        from itertools import zip_longest

        selected = self.live_list.selection()
        item = self.live_targets.get(selected[0], {}) if selected else {}
        roster = item.get('roster')
        self.live_roster_status.set('Assigned players' if roster else
                                    'Roster unavailable' if selected else 'Select a match to see its assigned players.')
        children = self.live_roster_table.get_children()
        if children:
            self.live_roster_table.delete(*children)
        if roster:
            for blue,red in zip_longest(roster['blue'],roster['red'],fillvalue=''):
                self.live_roster_table.insert('',tk.END,values=(blue,red))

    def render_live_matches(self,matches):
        selected=self.live_list.selection()
        previous=selected[0]if selected else None
        scroll=self.live_list.yview()[0]
        self.live_targets={item['id']:item for item in matches}
        children=self.live_list.get_children()
        if children:self.live_list.delete(*children)
        for item in matches:
            self.live_list.insert('',tk.END,iid=item['id'],values=(
                'Match '+item['id'][:6].upper(), item['label']+('  ·  Locked' if item.get('locked') else ''),
                str(item['playerCount'])+' / '+str(item['playerCapacity']),
                str(item['spectatorCount'])+' / '+str(item['spectatorCapacity'])))
        if previous in self.live_targets:self.live_list.selection_set(previous)
        self.live_list.yview_moveto(scroll)
        if self.watch_id is None:
            self.live_status.set('Select a match.' if matches else 'No matches are live right now.')
        self.render_live_controls()
        self.render_live_roster()

    def refresh_live_matches(self, *, background=False):
        if self.controls_busy or self.closing or not self.live_browser_supported():return
        if background and self.busy:return
        if self.current_panel!='live'and self.watch_id is None:return
        watch_id=self.watch_id
        selected = self.live_list.selection()
        roster_match_id = selected[0] if selected else None
        def work():
            stopped=False
            if watch_id is not None:
                status=self.game.snapshot()['status']if self.game else'idle'
                if status in ('idle','stopped','finished','failed'):
                    if self.game:self.game.stop_spectating()
                    else:self.lobby.release_spectator(watch_id)
                    stopped=True
                else:self.lobby.spectator_target(watch_id)
            options = {'roster_match_id':roster_match_id} if roster_match_id else {}
            return self.lobby.live_matches(**options),stopped
        def refreshed(value):
            matches,stopped=value
            if stopped and self.watch_id==watch_id:self.watch_id=None
            self.render_live_matches(matches)
        self.run_async(work,refreshed,background=background)

    def live_tick(self):
        self.live_refresh_handle=None
        if self.closing:return
        self.refresh_live_matches(background=True)
        self.live_refresh_handle=self.root.after(3000,self.live_tick)

    def show_live_join_tip(self, _event):
        if self.live_join_tip is not None or not self.live_join_reason.get():
            return
        button = self.live_join_button
        tip = self.live_join_tip = tk.Toplevel(button)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f'+{button.winfo_rootx()}+{button.winfo_rooty() + button.winfo_height() + 4}')
        tk.Label(tip, textvariable=self.live_join_reason, bg=PANEL, fg=TEXT, padx=8, pady=4).pack()

    def hide_live_join_tip(self, _event=None):
        if self.live_join_tip is not None:
            self.live_join_tip.destroy()
            self.live_join_tip = None

    def join_live_selected(self):
        if self.live_join_button.cget('state') != 'normal':
            return
        selected = self.live_list.selection()
        if not selected:
            return
        match_id = selected[0]
        target = self.live_targets.get(match_id, {})
        team = ('auto', 'blue', 'red')[max(0, self.live_team.current())] if not target.get('rejoin') else 'auto'

        def joined(room):
            self.join_attempted_match = None
            self.render(room)
            self.show_panel('lobbies')

        self.enter_lobby(lambda name: self.lobby.join_match(match_id, name, team=team), success=joined)

    def spectate_selected(self):
        if self.controls_busy or self.closing or self.watch_id is not None:return
        selected=self.live_list.selection()
        item=self.live_targets.get(selected[0])if selected else None
        if item is None or item.get('canSpectate')is not True:return
        if self.game_status not in ('idle','stopped','finished','failed'):return
        try:
            name = self.player_name_for_action()
        except (ValueError, SteamIdentityError) as exc:
            self.live_status.set(str(exc))
            return
        def admitted(target):
            self.watch_id=target['watchId']
            self.live_status.set('Preparing spectator view…')
            def begin():
                if not self.game:self.game=self.game_factory(self.lobby)
                return self.game.start_spectating(target['watchId'])
            self.run_async(begin,lambda _:self.live_status.set('Opening spectator view…'))
        self.run_async(lambda: self.lobby.spectate(item['id'],name), admitted)

    def stop_watching(self):
        if self.controls_busy or self.closing or self.watch_id is None:return
        watch_id=self.watch_id
        def work():
            if self.game:return self.game.stop_spectating()
            return self.lobby.release_spectator(watch_id)
        def stopped(_):
            if self.watch_id==watch_id:self.watch_id=None
            self.live_status.set('Stopped watching.');self.render_live_controls()
        self.run_async(work,stopped)

    def refresh(self):
        self.refresh_handle=None
        if self.closing: return
        if self.room and not self.busy:
            code = self.room['code']

            def update(room):
                if self.room is not None and self.room['code'] == code:
                    self.render(room)

            self.run_async(lambda: self.lobby.action('state'), update, background=True)
        if not self.closing: self.refresh_handle=self.root.after(2000,self.refresh)

    def show_connection_info(self):
        """Explain the launcher's observable behavior and give players verification links."""
        if getattr(self, 'connection_window', None) is not None and self.connection_window.winfo_exists():
            self.connection_window.lift()
            self.connection_window.focus_set()
            return
        window = tk.Toplevel(self.root, bg=BG, padx=24, pady=20)
        self.connection_window = window
        window.title('About this launcher')
        window.transient(self.root)
        window.resizable(False, False)
        self.label(window, 'About this launcher', 19, True).pack(anchor='w')
        host = getattr(self.lobby, 'hostname', '')
        port = getattr(self.lobby, 'port', '')
        if host:
            endpoint = f'{host}:{port}' if port else host
            self.label(window, 'Community server', 12, True).pack(anchor='w', pady=(14, 2))
            self.label(window, endpoint, 11, color=ACCENT).pack(anchor='w')
        sections = (
            ('Connection', 'Starter talks to the community server for lobbies and matches. '
             'Direct hosting also uses the assigned game server for gameplay and optional proximity voice.'),
            ('Game files', 'You play using your installed copy of TRIBES 3. Starter prepares a separate '
             'game session. Builds with map downloads also cache community content and verify its hashes.'),
            ('Account and files', 'Sign in through Steam as usual. Starter does not ask for your Steam or Epic '
             'password. It can save settings and logs in your Windows user profile and stage files in your chosen workspace.'),
            ('Verify it yourself', 'Review the source, inspect the launcher and game processes in Task Manager, '
             'or scan a downloaded archive with your antivirus. If your download includes a published SHA-256, '
             'compare it with the hash of your file.'),
        )
        for title, text in sections:
            self.label(window, title, 12, True).pack(anchor='w', pady=(12, 2))
            body = self.label(window, text, 11, color=MUTED)
            body.configure(wraplength=465, justify='left')
            body.pack(anchor='w')
        links = tk.Frame(window, bg=BG)
        links.pack(fill='x', pady=(16, 0))
        self.button(links, 'Client source', lambda: webbrowser.open(
            'https://github.com/T24085/T3FrontEndClient'), False).pack(side='left')
        self.button(links, 'Close', window.destroy, False).pack(side='right')
        window.bind('<Escape>', lambda _event: window.destroy())
        window.focus_set()


    def show_connection_info_once(self):
        """Use the persistent entry after the first-run introduction."""
        profile = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.config')
        receipt = profile / 'Tribes3CommunityStarter' / 'connection-info-v1.seen'
        if receipt.exists():
            return
        self.show_connection_info()
        window = self.connection_window

        def remember(event):
            if event.widget is not window:
                return
            try:
                receipt.parent.mkdir(parents=True, exist_ok=True)
                receipt.touch()
            except OSError:
                pass

        window.bind('<Destroy>', remember, add='+')

    def close(self):
        if self.closing: return
        self.closing = True
        for handle in self.notice_timers.values():
            self.root.after_cancel(handle)
        self.notice_timers.clear()
        self.backdrop.close()
        if self.map_sync is not None:
            self.map_sync.cancelled.set()
        for name in ('poll_handle','refresh_handle','copy_reset_handle','live_refresh_handle','steam_retry_handle'):
            handle=getattr(self,name,None)
            if handle is not None:
                self.root.after_cancel(handle)
                setattr(self,name,None)
        lobby,game,watch_id = self.lobby,self.game,self.watch_id
        match = self.room.get('match') if self.room is not None else None
        keep_membership = isinstance(match, dict) and match.get('status') in ('starting', 'ready')
        if game:
            game.stop()
        def release():
            try:
                if watch_id is not None:
                    if game:game.stop_spectating()
                    else:lobby.release_spectator(watch_id)
            except Exception:
                pass
            if not keep_membership:
                try:
                    lobby.action('leave')
                except Exception:
                    pass
        self.close_worker = threading.Thread(target=release,daemon=False)
        self.close_worker.start()
        self.root.destroy()


def main(*, ssl_context=None, on_ready=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hostname')
    parser.add_argument('--port', type=int)
    parser.add_argument('--server-address')
    parser.add_argument('--game-dir')
    parser.add_argument('--workspace')
    args = parser.parse_args()
    selected_game_directory, selected_workspace = installation_options(args.game_dir, args.workspace)
    settings_path = ROOT / 'client-settings.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.is_file() else {}
    hostname = args.hostname or settings.get('hostname')
    port = args.port or settings.get('port')
    server_address = args.server_address or settings.get('server_address')
    if not hostname or not port or not server_address:
        parser.error('Lobby hostname, port and server address are required.')
    policy = json.loads((CLIENT_PACKAGE/'connection-policy.json').read_text())
    lobby = CommunityClient(hostname,port,server_address,policy,ssl_context=ssl_context)
    sys.path.insert(0,str(CLIENT_PACKAGE/'lib'))
    from client_support import discover_game
    from steam_identity import read_steam_name
    from map_sync import MapSync
    map_sync = MapSync(lobby, CLIENT_PACKAGE, selected_workspace)
    def steam_name_loader():
        return read_steam_name(discover_game(selected_game_directory),CLIENT_PACKAGE/'base-game-manifest.json')
    def game_factory(current_lobby):
        source = discover_game(selected_game_directory)
        workspace = selected_workspace
        return CommunityGame(current_lobby,CLIENT_PACKAGE,source,workspace,workspace/'desktop-control',map_sync=map_sync)
    root = tk.Tk()
    from server_access import ServerAccess
    try:
        access = ServerAccess.load(CLIENT_PACKAGE)
    except (ValueError, OSError):
        access = None
    gui = Desktop(root,lobby,game_factory,steam_name_loader=steam_name_loader,server_access=access,map_sync=map_sync)
    if on_ready is not None:
        root.update_idletasks()
        on_ready()
    root.after_idle(gui.show_connection_info_once)
    root.after_idle(gui.offer_windows_retail_import, selected_workspace)
    root.mainloop()


if __name__ == '__main__':
    main()
