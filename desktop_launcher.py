"""Development-only Community Starter lobby and owned game launcher."""
import argparse
import json
import os
import webbrowser
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import simpledialog, ttk

from community_game import CommunityGame
from startup_paths import installation_options
from community_transport import (
    CommunityClient, CommunityError, CommunityConnectionError, DEFAULT_LOBBY_RULES,
    DEFAULT_MATCH_LIMITS, MAX_LOBBY_BOTS, MAX_MATCH_MINUTES, MAX_SCORE_LIMIT, validated_match_result,
)
from community_maps import BY_ID, options, read_options, LEGACY_MAPS
from map_sync_contract import CATALOG_VERSION, SESSION_VERSION, valid_sha

ROOT = Path(__file__).resolve().parent
CLIENT_PACKAGE = ROOT if (ROOT / 'connection-policy.json').is_file() else ROOT / 'dynamic-client-development'
BG, PANEL, TEXT, MUTED, ACCENT = '#0a111b', '#132335', '#eff7ff', '#9fb3c6', '#4be4c1'
SCOREBOARD_COLUMNS = (
    ('name', 'Player', 165),
    ('team', 'Team', 64),
    ('kills', 'Kills', 55),
    ('deaths', 'Deaths', 60),
    ('assists', 'Assists', 61),
    ('captures', 'Caps', 55),
    ('returns', 'Returns', 66),
    ('flagGrabs', 'Grabs', 58),
    ('flagHeldSeconds', 'Flag time', 78),
)


def starter_version(package=ROOT):
    try:
        manifest = json.loads((package / 'package-manifest.json').read_bytes())
        if isinstance(manifest, dict):
            revision = manifest.get('starter_update_revision')
            if type(revision) is int and revision > 0:
                return f'Starter r{revision}'
            release = manifest.get('release_id')
            if isinstance(release, str) and release.strip():
                return f'Starter {release}'
    except (OSError, ValueError):
        pass
    return 'Starter r0 · base build'


def match_phase_text(room):
    if room is None:
        return 'Create a lobby or enter a code.'
    restart = room.get('restart')
    if isinstance(restart, dict):
        stage = restart.get('stage')
        if stage == 'countdown':
            return f"Restarting in {restart['seconds']}s · {restart['reason']}"
        if stage in ('draining', 'starting'):
            return f"Match restarting · {restart['reason']}"
        if stage == 'failed':
            return f"Restart failed · {restart['error']}"
    result = match_result_for(room)
    match = room.get('match')
    if result and isinstance(match, dict) and match.get('id') == result['matchId']:
        scores = result['scores']
        return f"Final score   Blue {scores['blue']} – {scores['red']} Red"
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


def match_result_for(state):
    try:
        return validated_match_result((state or {}).get('lastResult'))
    except ValueError:
        return None


class Desktop:
    def __init__(self, root, lobby, game_factory, *, steam_name_loader=None, server_access=None, map_sync=None):
        self.root, self.lobby, self.game_factory = root, lobby, game_factory
        self.steam_name_loader = steam_name_loader
        self.map_sync = map_sync
        self.maps_panel = None
        self.lobby_map_target = None
        self.game = None
        self.room = None
        self.result_window = None
        self.pending_map = None
        self.map_inflight = None
        self.map_retry_count = 0
        self.map_retry_at = 0
        self.watch_id = None
        self.game_status = 'idle'
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
        root.title('TRIBES 3 • Community Starter')
        root.geometry('1030x800')
        root.minsize(850, 570)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TCombobox', fieldbackground='#20374a', background='#20374a', foreground=TEXT, arrowcolor=ACCENT, padding=8)
        style.configure('Live.Treeview',background='#0b1a29',fieldbackground='#0b1a29',foreground=TEXT,
                        rowheight=28,font=('Segoe UI',10))
        style.configure('Live.Treeview.Heading',background='#20374a',foreground=TEXT,font=('Segoe UI',9,'bold'))
        style.map('Live.Treeview',background=[('selected','#31566c')])
        self.name = tk.StringVar()
        self.code = tk.StringVar()
        self.map_name = tk.StringVar(value='Stonehenge')
        self.status = tk.StringVar(value='Checking community service…')
        self.room_heading = tk.StringVar(value='Not in a lobby')
        self.phase = tk.StringVar(value='Create a lobby or enter a code.')
        self.preparation = tk.StringVar(value='')
        self.allow_spectators = tk.BooleanVar(value=True)
        self.flag_indicators = tk.BooleanVar(value=False)
        self.fall_damage = tk.BooleanVar(value=False)
        self.allow_bots = tk.BooleanVar(value=False)
        self.bot_count = tk.StringVar(value='2')
        self.retail_capture_point = tk.BooleanVar(value=True)
        self.live_status = tk.StringVar(value='Checking live matches…')
        side = tk.Frame(root, bg='#0d1927', width=198)
        self.sidebar = side
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        icon_path = ROOT / 'branding/clan-wars.png'
        if icon_path.is_file():
            root.title('Tribes Rivals: Clan Wars (community mod)')
            self.clan_wars_icon = tk.PhotoImage(master=root, file=str(icon_path))
            root.iconphoto(True, self.clan_wars_icon)
            self.clan_wars_logo = self.clan_wars_icon.subsample(8)
            title = self.label(side, 'Clan Wars', 18, True, bg='#0d1927')
            title.configure(image=self.clan_wars_logo, compound='left')
            title.pack(anchor='w', padx=24, pady=(36, 0))
            caption = self.label(side, 'TRIBES RIVALS  \u00b7  COMMUNITY MOD', 9, color=ACCENT, bg='#0d1927')
            caption.configure(wraplength=165, justify='left')
            caption.pack(anchor='w', padx=26, pady=(4, 32))
        else:
            self.label(side, 'TRIBES 3', 25, True, bg='#0d1927').pack(anchor='w', padx=24, pady=(36, 0))
            self.label(side, 'COMMUNITY STARTER', 9, color=ACCENT, bg='#0d1927').pack(anchor='w', padx=26, pady=(4, 32))
        self.lobbies_nav=self.button(side,'Create Lobby',lambda:self.show_panel('lobbies'),False)
        self.lobbies_nav.pack(fill='x',padx=18,pady=(0,6))
        self.live_nav=self.button(side,'Server Browser',lambda:self.show_panel('live'),False)
        self.live_nav.pack(fill='x',padx=18)
        if self.map_sync is not None:
            self.button(side, 'Maps', lambda: self.show_panel('maps'), False).pack(fill='x', padx=18, pady=(6, 0))
        self.button(side, 'About this launcher', self.show_connection_info, False).pack(
            fill='x', padx=18, pady=(6, 0))
        if server_access is not None:
            from server_access import show_setup
            self.access_button = self.button(side, 'Set up server access', lambda: show_setup(self, server_access), False)
            self.access_button.pack(fill='x', padx=18, pady=(20, 0))
        self.label(side, starter_version(), 10, color=MUTED, bg='#0d1927').pack(side='bottom', anchor='w', padx=26, pady=24)
        tk.Label(side,textvariable=self.preparation,bg='#0d1927',fg=MUTED,font=('Segoe UI',10),
                 anchor='w',justify='left',wraplength=175).pack(side='bottom',anchor='w',padx=26,pady=(0,12))
        if self.map_sync is not None:
            self.map_status = tk.StringVar(value='')
            tk.Label(side,textvariable=self.map_status,bg='#0d1927',fg=MUTED,font=('Segoe UI',10),
                     anchor='w',justify='left',wraplength=175).pack(side='bottom',anchor='w',padx=26,pady=(0,12))
            self.map_progress = ttk.Progressbar(side, mode='determinate')
        self.settings_nav = None
        if sys.platform == 'win32':
            self.settings_nav = self.button(side, 'Settings', self.show_settings, False)
            self.settings_nav.pack(fill='x', padx=18, pady=(6, 0))
        main = tk.Frame(root, bg=BG)
        self.lobby_panel=main
        main.pack(side='left', fill='both', expand=True, padx=20, pady=14)
        self.lobby_layout = None
        self.entry_open = True
        self.advanced_open = False
        self.stacked_lobby_fields = None
        self.room_action_layout = None
        self.room_action_spacer = None
        self.play_strip = tk.Frame(main, bg=PANEL, padx=10, pady=5)
        self.play_strip.pack(fill='x')
        self.entry_toggle = self.button(self.play_strip, 'Join or create lobby ▸',
                                        lambda: self.set_entry_open(not self.entry_open), False)
        self.entry_toggle.configure(pady=5)
        self.play_actions = tk.Frame(self.play_strip, bg=PANEL)
        self.play_actions.pack(side='right')
        entry = self.entry_panel = tk.Frame(main, bg=PANEL, padx=12, pady=8)
        entry.pack(fill='x')
        self.label(entry, 'STEAM PLAYER NAME' if steam_name_loader else 'YOUR PLAYER NAME', 9, color=ACCENT, bg=PANEL).grid(row=0,column=0,sticky='w')
        self.label(entry, 'LOBBY CODE', 9, color=ACCENT, bg=PANEL).grid(row=0,column=1,sticky='w',padx=(12,0))
        self.name_entry = tk.Entry(entry,textvariable=self.name,font=('Segoe UI',12),bg='#20374a',fg=TEXT,insertbackground=TEXT,relief='flat')
        self.name_entry.grid(row=1,column=0,sticky='ew',ipady=7,pady=(4,8))
        self.code_entry = tk.Entry(entry,textvariable=self.code,font=('Segoe UI',12),bg='#20374a',fg=TEXT,insertbackground=TEXT,relief='flat')
        self.code_entry.grid(row=1,column=1,sticky='ew',ipady=7,padx=(12,0),pady=(4,8))
        entry.columnconfigure(0,weight=1);entry.columnconfigure(1,weight=1)
        self.create_button = self.button(entry,'Create lobby',self.create)
        self.create_button.grid(row=2,column=0,sticky='w')
        self.lock_lobby = tk.BooleanVar(value=False)
        self.lobby_lock = tk.Checkbutton(entry, text='Lock lobby after start', variable=self.lock_lobby,
            bg=PANEL, fg=TEXT, selectcolor='#20374a', activebackground=PANEL, activeforeground=TEXT)
        self.join_button = self.button(entry,'Join lobby',self.join,False)
        self.join_button.grid(row=2,column=1,sticky='w',padx=(12,0))
        card = self.room_card = tk.Frame(main, bg=PANEL, padx=14, pady=9)
        heading = tk.Frame(card,bg=PANEL)
        heading.pack(fill='x')
        self.copy_code_button = self.button(heading,'Copy lobby code',self.copy_lobby_code,False)
        self.copy_code_button.configure(pady=3)
        self.copy_code_button.pack(side='right',padx=(12,0))
        tk.Label(heading,textvariable=self.room_heading,bg=PANEL,fg=TEXT,font=('Segoe UI',17,'bold'),anchor='w').pack(side='left',fill='x',expand=True)
        tk.Label(card,textvariable=self.phase,bg=PANEL,fg=MUTED,font=('Segoe UI',10),anchor='w').pack(fill='x',pady=(2,8))
        self.match_fields = fields = tk.Frame(card, bg=PANEL)
        fields.pack(fill='x', pady=(0, 5))
        fields.columnconfigure(0, weight=2)
        fields.columnconfigure((1, 2), weight=1)
        self.map_field = maprow = tk.Frame(fields, bg=PANEL)
        maprow.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.label(maprow, 'MAP', 9, color=ACCENT, bg=PANEL).pack(anchor='w', pady=(0, 3))
        self.map_options=options(LEGACY_MAPS)
        self.map_combo = ttk.Combobox(maprow,textvariable=self.map_name,values=tuple(item['label'] for item in self.map_options), width=15, state='disabled')
        self.map_combo.pack(fill='x')
        self.map_combo.bind('<<ComboboxSelected>>',lambda e:self.choose_map())
        self.rule_heading = tk.Frame(card, bg=PANEL)
        self.rule_heading.pack(fill='x', pady=(0, 5))
        self.rule_heading.columnconfigure(1, weight=1)
        self.advanced_button = self.button(self.rule_heading, 'Advanced rules ▸',
                                           self.toggle_advanced_rules, False)
        self.advanced_button.configure(pady=3)
        self.advanced_button.grid(row=0, column=0, sticky='w')
        self.advanced_button.grid_remove()
        self.rules_row = tk.Frame(card, bg=PANEL)
        self.rules_row.columnconfigure((0, 1, 2), weight=1)
        self.spectator_toggle=tk.Checkbutton(self.rules_row,text='Allow spectators',variable=self.allow_spectators,
            command=self.toggle_spectators,bg=PANEL,fg=TEXT,selectcolor='#20374a',activebackground=PANEL,
            activeforeground=TEXT,font=('Segoe UI',9))
        self.spectator_toggle.grid(row=1, column=0, sticky='w')
        self.spectator_toggle.grid_remove()
        self.side_row = tk.Frame(fields, bg=PANEL)
        self.side_row.grid(row=0, column=1, sticky='ew', padx=(0, 10))
        self.label(self.side_row, 'BLUE STARTING SIDE', 9, color=ACCENT, bg=PANEL).pack(anchor='w', pady=(0, 3))
        self.blue_side = tk.StringVar(value='Side A')
        self.side_combo = ttk.Combobox(self.side_row, textvariable=self.blue_side,
                                       values=('Side A', 'Side B'), width=8, state='disabled')
        self.side_combo.pack(fill='x')
        self.side_combo.bind('<<ComboboxSelected>>', self.choose_side)
        self.red_side = tk.StringVar(value='Red starts on Side B')
        self.side_summary = tk.Label(self.rule_heading, textvariable=self.red_side, bg=PANEL, fg=MUTED,
                                     anchor='e', justify='right', wraplength=360)
        self.side_summary.grid(row=0, column=1, sticky='e')
        roster_frame = self.roster_frame = tk.Frame(card,bg=PANEL)
        roster_frame.pack(fill='both', expand=True, pady=(4, 0))
        check_style = dict(bg=PANEL,fg=TEXT,selectcolor='#20374a',activebackground=PANEL,
                           activeforeground=TEXT,font=('Segoe UI',9))
        self.flag_toggle = tk.Checkbutton(self.rules_row,text='Flag indicators',variable=self.flag_indicators,
            command=lambda:self.call_action('rules',flagIndicators=self.flag_indicators.get()),**check_style)
        self.flag_toggle.grid(row=0, column=0, sticky='w')
        self.fall_toggle = tk.Checkbutton(self.rules_row, text='Fall damage', variable=self.fall_damage,
            command=lambda: self.call_action('rules', fallDamage=self.fall_damage.get()), **check_style)
        self.fall_toggle.grid(row=0, column=1, sticky='w')
        self.fall_toggle.grid_remove()
        bots = tk.Frame(self.rules_row, bg=PANEL)
        bots.grid(row=0, column=2, sticky='w')
        self.bot_toggle = tk.Checkbutton(bots,text='Allow bots',variable=self.allow_bots,
            command=self.change_bots,**check_style)
        self.bot_toggle.pack(side='left')
        self.bot_spinner = ttk.Spinbox(bots,from_=1,to=MAX_LOBBY_BOTS,textvariable=self.bot_count,
                                       width=3,state='disabled',command=self.change_bots)
        self.bot_spinner.pack(side='left',padx=(2,10))
        self.capture_toggle = tk.Checkbutton(self.rules_row,text='Retail capture point',variable=self.retail_capture_point,
            command=lambda:self.call_action('rules',retailCapturePoint=self.retail_capture_point.get()),**check_style)
        self.capture_toggle.grid(row=1, column=1, columnspan=2, sticky='w')
        self.limits_row = tk.Frame(fields, bg=PANEL)
        self.limits_row.grid(row=0, column=2, sticky='ew')
        self.limits_row.columnconfigure((0, 1), weight=1, uniform='limits')
        self.label(self.limits_row, 'SCORE LIMIT (CAPS)', 9, color=ACCENT, bg=PANEL).grid(row=0, column=0, sticky='w', pady=(0, 3))
        self.score_limit = ttk.Combobox(self.limits_row,
            values=('Map default', 'Unlimited', *(str(value) for value in range(1, MAX_SCORE_LIMIT + 1))),
            width=9, state='disabled')
        self.score_limit.grid(row=1, column=0, sticky='ew', padx=(0, 10))
        self.label(self.limits_row, 'TIME LIMIT (MIN)', 9, color=ACCENT, bg=PANEL).grid(row=0, column=1, sticky='w', pady=(0, 3))
        self.match_minutes = ttk.Combobox(self.limits_row,
            values=('Map default', *(str(value) for value in range(1, MAX_MATCH_MINUTES + 1))),
            width=9, state='disabled')
        self.match_minutes.grid(row=1, column=1, sticky='ew')
        for control in (self.score_limit, self.match_minutes):
            control.bind('<<ComboboxSelected>>', self.change_match_limits)
        self.rosters = {}
        self.roster_players = {}
        team_frames = {}
        roster_frame.columnconfigure((0, 1), weight=1, uniform='teams')
        roster_frame.rowconfigure(0, weight=1)
        for team, label, color, col in (('blue', 'Team Blue', '#78b8ff', 0),
                                         ('red', 'Team Red', '#ff9393', 1),
                                         (None, 'Unassigned', MUTED, 0)):
            frame = team_frames[team] = tk.Frame(roster_frame, bg=PANEL)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)
            frame.grid(row=1 if team is None else 0, column=col, columnspan=2 if team is None else 1,
                       sticky='nsew', padx=(0, 3) if team == 'blue' else (3, 0) if team == 'red' else 0)
            self.label(frame, label, 10, True, color=color, bg=PANEL).grid(row=0, column=0, columnspan=2, sticky='w')
            roster = tk.Listbox(frame, bg='#0b1a29', fg=TEXT, selectbackground='#31566c',
                                font=('Segoe UI', 11), relief='flat', width=1,
                                height=1 if team is None else 2, exportselection=False)
            scroll = ttk.Scrollbar(frame, orient='vertical', command=roster.yview)
            roster.configure(yscrollcommand=scroll.set)
            roster.grid(row=1, column=0, columnspan=2, sticky='nsew', padx=(0, scroll.winfo_reqwidth()))
            scroll.place(in_=roster, relx=1, relheight=1, anchor='nw')
            roster.bind('<<ListboxSelect>>', lambda _event, box=roster: self.select_roster(box))
            self.rosters[team] = roster
            self.roster_players[team] = []
        for team, join_label, move_label in (
            ('blue', 'Join blue', 'Move to blue'), ('red', 'Join red', 'Move to red'),
        ):
            team_actions = tk.Frame(team_frames[team], bg=PANEL)
            team_actions.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(5, 0))
            team_actions.columnconfigure((0, 1), weight=1, uniform='actions')
            join = self.button(team_actions, join_label, lambda selected=team: self.call_action('team', team=selected), False)
            move = self.button(team_actions, move_label, lambda selected=team: self.move(selected), False)
            for column, button in enumerate((join, move)):
                button.configure(padx=5, pady=3)
                button.grid(row=0, column=column, sticky='ew', padx=(0, 4) if column == 0 else 0)
            if team == 'blue':
                self.blue_button, self.move_blue = join, move
            else:
                self.red_button, self.move_red = join, move
        self.team_action_labels = {button: button.cget('text') for button in (
            self.blue_button, self.move_blue, self.red_button, self.move_red)}
        actions = self.room_actions = tk.Frame(main, bg=BG)
        self.show_restart_action = False
        self.show_result_action = False
        self.start_button = self.button(actions,'Start match',lambda:self.call_action('start'))
        self.game_button = self.button(actions,'Join game',self.join_game)
        self.stop_button = self.button(actions,'Stop match',lambda:self.call_action('stop'),False)
        self.restart_button = self.button(actions, 'Restart match', self.restart_match, False)
        self.reset_button = self.button(actions,'New setup',lambda:self.call_action('reset'),False)
        self.leave_button = self.button(actions,'Leave',lambda:self.call_action('leave'),False)
        self.result_button = self.button(actions, 'Match results',
                                         lambda: self.show_match_result(match_result_for(self.room)), False)
        self.room_status = tk.Label(main, textvariable=self.status, bg=BG, fg=MUTED, font=('Segoe UI', 10),
                                    anchor='w', justify='left')
        main.bind('<Configure>', self.layout_play, add='+')
        self.live_panel=tk.Frame(root,bg=BG)
        self.label(self.live_panel,'Server Browser',27,True).pack(anchor='w')
        self.live_summary=self.label(self.live_panel,'Left click for next player, right click for previous. F7 for first person, F8 for chase, or middle click to switch views.',
                   11,color=MUTED)
        self.live_summary.configure(wraplength=500,justify='left')
        self.live_summary.pack(anchor='w',pady=(4,18))
        create_card = tk.Frame(self.live_panel, bg=PANEL, padx=14, pady=12)
        create_card.pack(fill='x', pady=(0, 12))
        self.create_map_name = tk.StringVar()
        self.browser_name = tk.Entry(create_card, textvariable=self.name, width=16, bg='#20374a',
                                     fg=TEXT, insertbackground=TEXT, relief='flat')
        self.browser_name.pack(side='left', ipady=6, padx=(0, 8))
        self.create_map = ttk.Combobox(create_card, textvariable=self.create_map_name, state='disabled')
        self.create_map.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.browser_create_button = self.button(create_card, 'Create lobby', self.create)
        self.browser_create_button.pack(side='right')
        self.browser_lock = tk.Checkbutton(self.live_panel, text='Lock lobby after start', variable=self.lock_lobby,
            bg=BG, fg=TEXT, selectcolor='#20374a', activebackground=BG, activeforeground=TEXT)
        live_card = self.live_card = tk.Frame(self.live_panel, bg=PANEL, padx=18, pady=18)
        live_card.pack(fill='both',expand=True)
        self.live_list=ttk.Treeview(live_card,columns=('match','map','players','spectators','limits'),show='headings',height=10,selectmode='browse',style='Live.Treeview')
        for key,title,width in (('match','Match',90),('map','Map',180),('players','Assigned players',115),('spectators','Spectator seats',115),('limits','Score / time',135)):
            self.live_list.heading(key,text=title);self.live_list.column(key,width=width,minwidth=70,stretch=True)
        live_scroll=ttk.Scrollbar(live_card,orient='vertical',command=self.live_list.yview)
        self.live_list.configure(yscrollcommand=live_scroll.set)
        live_scroll.pack(side='right',fill='y');self.live_list.pack(side='left',fill='both',expand=True)
        self.live_list.bind('<<TreeviewSelect>>',lambda event:self.render_live_controls())
        live_actions=tk.Frame(self.live_panel,bg=BG);live_actions.pack(fill='x',pady=(14,0))
        self.spectate_button=self.button(live_actions,'Spectate',self.spectate_selected)
        self.spectate_button.pack(side='left',padx=(0,8))
        self.stop_watch_button=self.button(live_actions,'Stop watching',self.stop_watching,False)
        self.stop_watch_button.pack(side='left',padx=(0,8))
        self.live_refresh_button=self.button(live_actions,'Refresh',self.refresh_live_matches,False)
        self.live_refresh_button.pack(side='left')
        self.live_join_row = tk.Frame(self.live_panel, bg=BG)
        self.live_join_button = self.button(self.live_join_row, 'Join match', self.join_live_selected)
        self.live_join_button.pack(side='left', padx=(0, 8))
        self.live_join_tip = None
        self.live_join_button.bind('<Enter>', self.show_live_join_tip)
        self.live_join_button.bind('<Leave>', self.hide_live_join_tip)
        self.live_join_row.bind('<Unmap>', self.hide_live_join_tip)
        self.live_team = ttk.Combobox(self.live_join_row, width=16, state='disabled')
        self.live_team.pack(side='left')
        self.live_join_reason = tk.StringVar()
        tk.Label(self.live_join_row, textvariable=self.live_join_reason, bg=BG, fg=MUTED,
                 anchor='w', justify='left', wraplength=260).pack(side='left', padx=8)
        self.live_status_label = tk.Label(self.live_panel, textvariable=self.live_status, bg=BG, fg=MUTED,
                                         font=('Segoe UI',10), anchor='w', justify='left', wraplength=650)
        self.live_status_label.pack(fill='x', pady=(12,0))
        if self.map_sync is not None:
            self.build_maps_panel()
        self.render_live_controls()
        self.render(None)
        if steam_name_loader:
            self.run_async(steam_name_loader, self.set_steam_name)
        else:
            self.run_async(self.lobby.capabilities, self.set_capabilities)
        self.poll_handle=root.after(150,self.poll)
        self.refresh_handle=root.after(2000,self.refresh)
        self.live_refresh_handle=root.after(3000,self.live_tick)


    def show_lobby_controls(self, in_room):
        if self.lobby_layout == in_room:
            return
        self.lobby_layout = in_room
        self.entry_toggle.pack_forget()
        if in_room:
            self.entry_toggle.pack(side='left')
            self.set_entry_open(False)
            self.room_actions.pack(side='bottom', fill='x', padx=0, pady=(10, 0))
            self.room_status.pack(side='bottom', before=self.room_actions, fill='x', pady=(5, 0))
            self.room_card.pack(fill='both', expand=True, pady=(8, 0))
        else:
            self.advanced_open = False
            self.room_card.pack_forget()
            self.room_actions.pack_forget()
            self.room_status.pack(side='bottom', fill='x', pady=(5, 0))
            self.set_entry_open(True)

    def set_entry_open(self, open_form):
        self.entry_open = open_form
        self.entry_toggle.configure(text='Join or create lobby ' + ('▾' if open_form else '▸'))
        if open_form:
            self.entry_panel.pack(fill='x', after=self.play_strip)
        else:
            self.entry_panel.pack_forget()

    def toggle_advanced_rules(self):
        self.advanced_open = not self.advanced_open
        self.show_advanced_rules()

    def show_advanced_rules(self):
        available = self.lobby_layout and (
            self.caps.get('matchRulesEnabled') is True or self.caps.get('spectateEnabled') is True)
        if available:
            self.advanced_button.grid()
        else:
            self.advanced_button.grid_remove()
        self.advanced_button.configure(text='Advanced rules ' + ('▾' if self.advanced_open else '▸'))
        if available and self.advanced_open:
            self.rules_row.pack(fill='x', before=self.roster_frame, pady=(0, 5))
        else:
            self.rules_row.pack_forget()

    def layout_play(self, event):
        width = event.width
        compact_sidebar = width + self.sidebar.winfo_width() < 1150
        self.resize_lobby_sidebar(compact_sidebar)
        field_width = sum(field.winfo_reqwidth() for field in (self.map_field, self.side_row, self.limits_row))
        stacked = width < field_width + 52
        if stacked != self.stacked_lobby_fields:
            self.stacked_lobby_fields = stacked
            self.map_field.grid_configure(row=0, column=0, columnspan=2 if stacked else 1)
            self.reflow_optional_field(self.side_row, row=0, column=2 if stacked else 1)
            self.reflow_optional_field(self.limits_row, row=1 if stacked else 0, column=0 if stacked else 2,
                                       columnspan=3 if stacked else 1, pady=(5, 0) if stacked else 0)
        for button, label in self.team_action_labels.items():
            button.configure(text=label if width >= 700 else ('Join team' if label.startswith('Join') else 'Move here'))
        self.room_status.configure(wraplength=max(width - 8, 1))
        self.layout_room_actions(width)

    @staticmethod
    def reflow_optional_field(field, **position):
        visible = bool(field.winfo_manager())
        field.grid_configure(**position)
        if not visible:
            field.grid_remove()

    def layout_room_actions(self, width=None):
        if width is None:
            width = self.lobby_panel.winfo_width()
        buttons = [self.start_button, self.game_button, self.stop_button]
        if self.show_restart_action:
            buttons.append(self.restart_button)
        buttons.append(self.reset_button)
        if self.show_result_action:
            buttons.append(self.result_button)
        all_buttons = (*buttons, self.leave_button)
        wrap = sum(button.winfo_reqwidth() + 6 for button in all_buttons) + 16 > width
        key = (all_buttons, wrap)
        if key == self.room_action_layout:
            return
        self.room_action_layout = key
        for button in self.room_actions.grid_slaves():
            button.grid_forget()
        if self.room_action_spacer is not None:
            self.room_actions.columnconfigure(self.room_action_spacer, weight=0)
        for index, button in enumerate(buttons):
            row = int(wrap and index >= 3)
            button.grid(row=row, column=(index - 3 if row else index), sticky='w',
                        padx=(0, 6), pady=(4, 0) if row else 0)
        spacer = 3 if wrap else len(buttons)
        self.room_action_spacer = spacer
        self.room_actions.columnconfigure(spacer, weight=1)
        self.leave_button.grid(row=0, column=spacer+1, sticky='e')

    def resize_lobby_sidebar(self, compact):
        width = 198 if compact else 225
        if int(self.sidebar.cget('width')) != width:
            self.sidebar.configure(width=width)


    def label(self,parent,text,size=11,bold=False,color=TEXT,bg=BG):
        return tk.Label(parent,text=text,bg=bg,fg=color,font=('Segoe UI',size,'bold' if bold else 'normal'),anchor='w')

    def button(self,parent,text,command,primary=True):
        return tk.Button(parent,text=text,command=command,bg=ACCENT if primary else '#263e52',fg=BG if primary else TEXT,
                         activebackground='#6ff0d4',relief='flat',padx=10,pady=7,font=('Segoe UI',10,'bold'))

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

    def poll(self):
        self.poll_handle=None
        if self.closing: return
        if self.map_sync is not None:
            self.map_status.set(self.map_sync.status)
            progress = self.map_sync.progress
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
                restart = self.room.get('restart') if self.room else None
                if (isinstance(restart, dict) and restart.get('stage') in ('draining', 'starting', 'complete')
                        and state['status'] in ('starting', 'playing') and state.get('role') == 'player'
                        and state.get('matchId') == restart.get('matchId')
                        and self.game.stop_replaced_match(restart['matchId'])):
                    self.game_status = 'stopping'
                    state = dict(state, status='stopping', progress='Closing the previous match…')
                if state['status'] in ('starting','playing','stopping'):
                    self.status.set(state.get('progress') or {'starting':'Opening game…','playing':'Game connected.','stopping':'Closing game…'}[state['status']])
                    if self.watch_id is not None:
                        self.live_status.set(state.get('progress') or {'starting':'Opening spectator view…','playing':'Watching match.','stopping':'Closing spectator view…'}[state['status']])
                elif state['error']:
                    self.status.set(state['error'])
                elif previous_status != self.game_status and state.get('progress'):
                    self.status.set(state['progress'])
                preparation=state.get('preparation')
                if isinstance(preparation,dict):
                    self.preparation.set(preparation.get('error') or preparation.get('progress') or '')
            except Exception as exc: self.status.set(str(exc))
        self.maybe_auto_join()
        self.render_live_controls()
        if self.current_panel == 'maps':
            self.render_map_controls()
        if not self.closing: self.poll_handle=self.root.after(150,self.poll)

    def set_capabilities(self, caps):
        self.caps = caps
        self.capabilities_loaded = True
        if self.map_sync is not None:
            self.map_sync.start(caps.get('mapFileSync'), session_version=caps.get('mapSessionSync'))
        self.status.set('Community service connected.')
        self.render(self.room)
        self.render_live_controls()
        if self.room is None and caps.get('lobbyResumeEnabled') is True:
            def resumed(room):
                self.render(room)
                if self.current_panel == 'maps':
                    self.refresh_maps()
            self.run_async(self.lobby.resume, resumed)
        elif self.current_panel=='live':
            self.refresh_live_matches()
        elif self.current_panel == 'maps':
            self.refresh_maps()

    def choose_map(self):
        selected=self.map_name.get()
        matches=[item['id'] for item in self.map_options if item['label']==selected]
        if len(matches)!=1:
            self.status.set('Choose an available map.');return
        if self.room is None or self.room['phase'] != 'setup':
            return
        self.pending_map = (self.room['code'], matches[0])
        self.map_retry_count = 0
        self.map_retry_at = 0
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

    def set_steam_name(self, name):
        self.name.set(name)
        self.run_async(self.lobby.capabilities, self.set_capabilities)

    def render(self, room):
        if (self.room or {}).get('code') != (room or {}).get('code'):
            self.reset_copy_feedback()
        self.room = room
        result = match_result_for(room)
        self.show_result_action = result is not None
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
        restart = room.get('restart') if in_room else None
        restarting = isinstance(restart, dict) and restart.get('stage') in ('countdown', 'draining', 'starting')
        can_restart = leader and self.caps.get('matchRestartEnabled') is True and phase in (
            'starting', 'ready', 'stopped', 'ended', 'failed')
        self.show_restart_action = can_restart
        self.restart_button.configure(state='normal' if can_restart and not restarting and not self.controls_busy else 'disabled')
        self.layout_room_actions()
        setup = in_room and phase=='setup'
        if not setup or not leader or self.pending_map is not None and self.pending_map[0] != room['code']:
            self.pending_map = None
        self.allow_spectators.set(room.get('allowSpectators',True) if in_room else True)
        if self.caps.get('spectateEnabled') is True:
            self.spectator_toggle.grid()
            self.spectator_toggle.configure(state='normal' if setup and leader else 'disabled')
        else:
            self.spectator_toggle.grid_remove()
        self.show_advanced_rules()
        for widget in (self.name_entry, self.code_entry, self.create_button, self.join_button,
                       self.browser_create_button): widget.configure(state='disabled' if in_room or self.controls_busy else 'normal')
        if self.steam_name_loader and not in_room and not self.controls_busy:
            self.name_entry.configure(state='readonly', readonlybackground='#20374a')
        if self.caps.get('privateLobbyAdmission') is True:
            self.lobby_lock.grid(row=3, column=0, sticky='w', pady=(4, 0))
            state = 'disabled' if in_room or self.controls_busy else 'normal'
            self.lobby_lock.configure(state=state)
            self.browser_lock.configure(state=state)
            if not self.browser_lock.winfo_manager():
                self.browser_lock.pack(anchor='w', before=self.live_card)
        else:
            self.lobby_lock.grid_remove()
            self.browser_lock.pack_forget()
        self.room_heading.set(('Lobby  '+room['code']+('  ·  Locked' if room.get('locked') else ''))
                              if in_room else 'Not in a lobby')
        self.browser_name.configure(state=('disabled' if in_room or self.controls_busy else
                                           'readonly' if self.steam_name_loader else 'normal'),
                                    readonlybackground='#20374a')
        self.phase.set(match_phase_text(room))
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
        self.map_options=available
        self.create_map.configure(values=tuple(sorted(labels.values(), key=str.casefold)), height=min(18, len(labels)),
                                  state='readonly' if not in_room and not self.controls_busy
                                  and self.caps.get('mapSessionSync') == SESSION_VERSION else 'disabled')
        if self.create_map_name.get() not in labels.values():
            self.create_map_name.set(next(iter(labels.values()), ''))
        self.map_combo.configure(values=tuple(item['label'] for item in available),height=min(18,len(available)),state='readonly' if setup and leader else 'disabled')
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
        match_finished = result and result['matchId'] == (room.get('match') or {}).get('id')
        join_pending = in_room and (room.get('match') or {}).get('status') == 'starting'
        can_join = (in_room and phase == 'ready' and not join_pending and not restarting
                    and not match_finished and not self.controls_busy
                    and self.pending_map is None and self.caps.get('gameClientReady'))
        self.game_button.configure(state='normal' if can_join else 'disabled')
        can_stop = leader and phase in ('starting', 'ready') and (not restarting or restart.get('replacementMatchId'))
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

    def show_match_result(self, result):
        if result is None:
            return
        if self.result_window is not None and self.result_window.winfo_exists():
            self.result_window.destroy()
        window = self.result_window = tk.Toplevel(self.root)
        window.title('Match results')
        window.configure(bg=BG)
        window.transient(self.root)
        window.bind('<Escape>', lambda _event: window.destroy())
        content = tk.Frame(window, bg=BG, padx=20, pady=18)
        content.pack(fill='both', expand=True)
        map_id = result['map']
        label = self.lobby.map_label(map_id) or map_id
        self.label(content, label, 20, True).pack(anchor='w')
        scores = result['scores']
        self.label(content, f"Blue {scores['blue']} – {scores['red']} Red", 15, True).pack(anchor='w', pady=(2, 14))
        if result['players']:
            body = tk.Frame(content, bg=PANEL)
            body.pack(fill='both', expand=True)
            keys = tuple(key for key, _, _ in SCOREBOARD_COLUMNS)
            board = ttk.Treeview(body, columns=keys, show='headings', style='Live.Treeview',
                                 height=min(12, len(result['players'])))
            for key, heading, width in SCOREBOARD_COLUMNS:
                board.heading(key, text=heading)
                board.column(key, width=width, minwidth=48, anchor='w' if key == 'name' else 'center')
            board.tag_configure('blue', foreground='#78b8ff')
            board.tag_configure('red', foreground='#ff9393')
            scroll = ttk.Scrollbar(body, orient='vertical', command=board.yview)
            board.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right', fill='y')
            board.pack(side='left', fill='both', expand=True)
            for player in sorted(result['players'], key=lambda row: (row['team'], row['name'].casefold())):
                team = player['team']
                stats = player['stats']
                minutes, seconds = divmod(int(stats['flagHeldSeconds']), 60)
                values = (player['name'], team.title(), *[stats[key] for key in keys[2:-1]],
                          f'{minutes}:{seconds:02d}')
                board.insert('', 'end', values=values, tags=(team,))
        self.button(content, 'Close', window.destroy, False).pack(anchor='e', pady=(12, 0))

    def create(self):
        def created(room):
            self.render(room)
            self.show_panel('lobbies')
        selected = next((item['id'] for item in self.map_options if item['label'] == self.create_map_name.get()), None)
        options = {'locked': self.lock_lobby.get()} if self.caps.get('privateLobbyAdmission') is True else {}
        if self.current_panel == 'live' and selected and self.caps.get('mapSessionSync') == SESSION_VERSION:
            options['map_id'] = selected
        def create(name):
            return self.lobby.create(name, **options)
        if self.steam_name_loader:
            self.enter_with_steam(create, success=created)
        else:
            name = self.name.get()
            self.run_async(lambda: create(name), created)

    def join(self):
        code, name = self.code.get().strip().upper(), self.name.get()
        if self.steam_name_loader:
            self.enter_with_steam(lambda name:self.lobby.join(code,name))
        else:
            self.run_async(lambda:self.lobby.join(code,name),self.render)

    def enter_with_steam(self, operation, *, success=None):
        def work():
            name=self.steam_name_loader()
            return name,operation(name)
        def entered(value):
            name,room=value
            self.name.set(name)
            (success or self.render)(room)
            if not self.capabilities_loaded:
                self.run_async(self.lobby.capabilities, self.set_capabilities)
        self.run_async(work,entered)
    def call_action(self,operation,**data):
        if operation == 'start' and self.pending_map is not None:
            self.status.set('Wait for the selected map to be confirmed.')
            return
        def work():
            if operation == 'leave' and self.game and self.game.snapshot()['status'] in ('starting','playing','stopping'):
                self.game.stop()
            return self.lobby.action(operation,**data)
        self.run_async(work,self.render)

    def restart_match(self):
        if self.room is None or self.restart_button.cget('state') != 'normal':
            return
        match = self.room.get('match')
        if not isinstance(match, dict) or not match.get('id'):
            return
        reason = simpledialog.askstring('Restart match',
            'Start a fresh round on the same map and teams. Enter a reason for everyone in the lobby.',
            parent=self.root)
        if reason is None:
            return
        if not reason.isprintable() or not 1 <= len(reason.strip()) <= 120:
            self.status.set('Enter a printable restart reason of 1–120 characters.')
            return
        self.call_action('restart', matchId=match['id'], reason=reason.strip())

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
            self.side_row.grid_remove()
            self.side_summary.grid_remove()
            return
        if not self.side_row.winfo_manager():
            self.side_row.grid()
        self.side_summary.grid()
        self.blue_side.set('Side ' + side)
        self.red_side.set('Red starts on Side A · In-game colors swap' if side == 'B'
                          else 'Red starts on Side B')
        self.side_combo.configure(state='readonly' if editable else 'disabled')

    def choose_side(self, _event=None):
        if self.side_combo.instate(('readonly',)):
            value = self.blue_side.get()
            if value in ('Side A', 'Side B'):
                self.call_action('rules', blueSide=value[-1])

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
            self.join_attempted_match = match_id

    def toggle_spectators(self):
        if self.room is not None and self.caps.get('spectateEnabled')is True:
            self.call_action('spectators',allow=self.allow_spectators.get())

    def render_match_rules(self, room, editable):
        if self.caps.get('matchRulesEnabled') is not True:
            self.limits_row.grid_remove()
            self.flag_toggle.grid_remove()
            self.fall_toggle.grid_remove()
            self.bot_toggle.master.grid_remove()
            self.capture_toggle.grid_remove()
            return
        self.flag_toggle.grid()
        self.bot_toggle.master.grid()
        self.capture_toggle.grid()
        rules = room.get('rules', DEFAULT_LOBBY_RULES) if room else DEFAULT_LOBBY_RULES
        self.flag_indicators.set(rules['flagIndicators'])
        self.fall_damage.set(rules.get('fallDamage') is True)
        if self.caps.get('fallDamageEnabled') is True:
            if not self.fall_toggle.winfo_manager():
                self.fall_toggle.grid()
            self.fall_toggle.configure(state='normal' if editable else 'disabled')
        else:
            self.fall_toggle.grid_remove()
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
        self.render_match_limits(room, editable)

    def render_match_limits(self, room, editable):
        if room is None or self.caps.get('matchLimitsEnabled') is not True:
            self.limits_row.grid_remove()
            return
        if not self.limits_row.winfo_manager():
            self.limits_row.grid()
        limits = room.get('matchLimits', DEFAULT_MATCH_LIMITS)
        score, minutes = limits['scoreLimit'], limits['matchMinutes']
        score_label = 'Unlimited' if score == 0 else str(score) if score is not None else 'Map default'
        self.score_limit.set(score_label)
        self.match_minutes.set(str(minutes) if minutes is not None else 'Map default')
        for control in (self.score_limit, self.match_minutes):
            control.configure(state='readonly' if editable else 'disabled')

    def change_match_limits(self, _event=None):
        score, minutes = self.score_limit.get(), self.match_minutes.get()
        self.call_action('rules', matchLimits={
            'scoreLimit': None if score == 'Map default' else 0 if score == 'Unlimited' else int(score),
            'matchMinutes': None if minutes == 'Map default' else int(minutes),
        })

    def change_bots(self):
        self.call_action('rules',botCount=int(self.bot_count.get()) if self.allow_bots.get() else 0)

    def show_panel(self,name):
        if self.closing:return
        self.current_panel=name
        self.lobby_panel.pack_forget();self.live_panel.pack_forget()
        if self.maps_panel is not None:
            self.maps_panel.pack_forget()
        panel = self.maps_panel if name == 'maps' else self.live_panel if name == 'live' else self.lobby_panel
        if name == 'lobbies':
            panel.pack(side='left', fill='both', expand=True, padx=20, pady=14)
        else:
            panel.pack(side='left', fill='both', expand=True, padx=32, pady=28)
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
        self.maps_table = ttk.Treeview(table, columns=tuple(key for key, _, _ in columns),
                                       show='headings', style='Live.Treeview', selectmode='browse')
        for key, title, width in columns:
            self.maps_table.heading(key, text=title)
            self.maps_table.column(key, width=width, minwidth=width-12)
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.maps_table.yview)
        self.maps_table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.maps_table.pack(side='left', fill='both', expand=True)
        self.maps_table.bind('<<TreeviewSelect>>', lambda _event: self.render_map_controls())
        self.map_rows = {}
        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(fill='x')
        self.map_download = self.button(buttons, 'Download', lambda: self.manage_map(False))
        self.map_download.pack(side='left', padx=(0, 8))
        self.map_remove = self.button(buttons, 'Remove download', lambda: self.manage_map(True), False)
        self.map_remove.pack(side='left', padx=(0, 8))
        self.map_refresh = self.button(buttons, 'Refresh', self.refresh_maps, False)
        self.map_refresh.pack(side='left')
        self.maps_notice = tk.StringVar()
        tk.Label(panel, textvariable=self.maps_notice, bg=BG, fg=MUTED, wraplength=530,
                 anchor='w', justify='left').pack(fill='x', pady=(10, 0))

    def selected_download(self):
        selection = self.maps_table.selection()
        return self.map_rows.get(selection[0]) if selection else None

    def render_map_controls(self):
        row = self.selected_download()
        enabled = self.map_sync.session_enabled and not self.controls_busy
        active = self.game_status not in ('idle', 'stopped', 'finished', 'failed')
        self.map_refresh.configure(state='normal' if enabled else 'disabled')
        self.map_download.configure(text='Update' if row and row['state'] == 'Update available' else 'Download',
                                    state='normal' if enabled and row and row['state'] != 'Downloaded' else 'disabled')
        self.map_remove.configure(state='normal' if enabled and row and row['removable'] and not active else 'disabled')

    def load_map_rows(self, operation=None):
        if not self.map_sync.session_enabled:
            self.maps_notice.set('Per-map downloads are unavailable on this server.')
            self.render_map_controls()
            return
        self.maps_notice.set('Checking map downloads…')

        def work():
            try:
                if operation is not None:
                    operation()
                return self.map_sync.local_maps(self.map_sync.map_index()), None
            except (CommunityError, ValueError, OSError) as exc:
                return None, str(exc)

        def loaded(result):
            rows, error = result
            if error is not None:
                self.maps_notice.set(error)
                self.render_map_controls()
                return
            selected = self.maps_table.selection()
            self.map_rows = {row['id']: row for row in rows}
            self.maps_table.delete(*self.maps_table.get_children())
            for row in rows:
                self.maps_table.insert('', 'end', iid=row['id'],
                                       values=(row['label'], row['gameTag'], f"{row['bytes']/1024**2:,.1f} MiB",
                                               row['manifestHash'][:8], row['state']))
            if selected and selected[0] in self.map_rows:
                self.maps_table.selection_set(selected[0])
            self.maps_notice.set('')
            self.render_map_controls()

        self.run_async(work, loaded)
        self.render_map_controls()

    def refresh_maps(self):
        self.load_map_rows()

    def manage_map(self, remove):
        row = self.selected_download()
        if row is None or self.controls_busy:
            return
        if remove:
            if not row['removable'] or self.game_status not in ('idle', 'stopped', 'finished', 'failed'):
                return
            self.load_map_rows(lambda: self.map_sync.remove_map(row['id']))
        elif row['state'] != 'Downloaded':
            self.load_map_rows(lambda: self.map_sync.sync_map(row['id'], row['contentHash'], row['manifestHash']))

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
        self.label(window, 'Game settings', 21, True).pack(anchor='w')
        description = self.label(
            window, 'Copy your retail key bindings, sensitivity, and game options. '
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
            status.set('Retail settings imported. They apply the next time you open the game.'
                       if changed else 'Your community settings already match the saved retail settings.')

        self.button(window, 'Import settings from retail', import_settings).pack(anchor='w')
        tk.Label(window, textvariable=status, bg=BG, fg=MUTED, font=('Segoe UI', 10),
                 justify='left', wraplength=420, anchor='w').pack(fill='x', pady=(12, 0))
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
        values = ('Auto Balance', *(f'{side.title()} ({counts[side]})' if side in counts else side.title()
                                    for side in ('blue', 'red')))
        if tuple(self.live_team['values']) != values:
            selected_team = self.live_team.current()
            self.live_team.configure(values=values)
            self.live_team.current(max(0, selected_team))
        self.live_team.configure(state='readonly' if ready and not returning else 'disabled')

    def render_live_matches(self,matches):
        selected=self.live_list.selection()
        previous=selected[0]if selected else None
        scroll=self.live_list.yview()[0]
        self.live_targets={item['id']:item for item in matches}
        children=self.live_list.get_children()
        if children:self.live_list.delete(*children)
        for item in matches:
            limits = item.get('matchLimits', DEFAULT_MATCH_LIMITS)
            score, minutes = limits['scoreLimit'], limits['matchMinutes']
            score_label = 'Unlimited' if score == 0 else f'{score} caps' if score is not None else 'Default score'
            time_label = f'{minutes} min' if minutes is not None else 'Default time'
            limit_label = 'Map defaults' if limits == DEFAULT_MATCH_LIMITS else f'{score_label} / {time_label}'
            self.live_list.insert('',tk.END,iid=item['id'],values=(
                'Match '+item['id'][:6].upper(), ('Locked · ' if item.get('locked') else '') + item['label'],
                str(item['playerCount'])+' / '+str(item['playerCapacity']),
                str(item['spectatorCount'])+' / '+str(item['spectatorCapacity']), limit_label))
        if previous in self.live_targets:self.live_list.selection_set(previous)
        self.live_list.yview_moveto(scroll)
        if self.watch_id is None:
            self.live_status.set('Select a match.' if matches else 'No matches are live right now.')
        self.render_live_controls()

    def refresh_live_matches(self, *, background=False):
        if self.controls_busy or self.closing or not self.live_browser_supported():return
        if background and self.busy:return
        if self.current_panel!='live'and self.watch_id is None:return
        watch_id=self.watch_id
        def work():
            stopped=False
            if watch_id is not None:
                status=self.game.snapshot()['status']if self.game else'idle'
                if status in ('idle','stopped','finished','failed'):
                    if self.game:self.game.stop_spectating()
                    else:self.lobby.release_spectator(watch_id)
                    stopped=True
                else:self.lobby.spectator_target(watch_id)
            return self.lobby.live_matches(),stopped
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

        if self.steam_name_loader:
            self.enter_with_steam(lambda name: self.lobby.join_match(match_id, name, team=team), success=joined)
        else:
            name = self.name.get()
            self.run_async(lambda: self.lobby.join_match(match_id, name, team=team), joined)

    def spectate_selected(self):
        if self.controls_busy or self.closing or self.watch_id is not None:return
        selected=self.live_list.selection()
        item=self.live_targets.get(selected[0])if selected else None
        if item is None or item.get('canSpectate')is not True:return
        if self.game_status not in ('idle','stopped','finished','failed'):return
        selected_name=self.name.get()
        def admit():
            name=self.steam_name_loader()if self.steam_name_loader else selected_name
            return name,self.lobby.spectate(item['id'],name)
        def admitted(value):
            name,target=value
            self.name.set(name);self.watch_id=target['watchId']
            self.live_status.set('Preparing spectator view…')
            def begin():
                if not self.game:self.game=self.game_factory(self.lobby)
                return self.game.start_spectating(target['watchId'])
            self.run_async(begin,lambda _:self.live_status.set('Opening spectator view…'))
        self.run_async(admit,admitted)

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
        if self.room and not self.busy and not self.closing:
            self.run_async(lambda:self.lobby.action('state'),self.render,background=True)
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
        if self.map_sync is not None:
            self.map_sync.cancelled.set()
        for name in ('poll_handle','refresh_handle','copy_reset_handle','live_refresh_handle'):
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
    root.mainloop()


if __name__ == '__main__':
    main()
