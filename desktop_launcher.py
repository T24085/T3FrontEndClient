"""Development-only Community Starter lobby and owned game launcher."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from community_game import CommunityGame
from startup_paths import installation_options
from community_transport import CommunityClient, CommunityError, CommunityConnectionError, DEFAULT_LOBBY_RULES, MAX_LOBBY_BOTS
from community_maps import BY_ID, options, read_options, LEGACY_MAPS
from map_sync_contract import CATALOG_VERSION

ROOT = Path(__file__).resolve().parent
CLIENT_PACKAGE = ROOT if (ROOT / 'connection-policy.json').is_file() else ROOT / 'dynamic-client-development'
BG, PANEL, TEXT, MUTED, ACCENT = '#0a111b', '#132335', '#eff7ff', '#9fb3c6', '#4be4c1'


def match_phase_text(room):
    if room is None:
        return 'Create a lobby or enter a code.'
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
    def __init__(self, root, lobby, game_factory, *, steam_name_loader=None, server_access=None, map_sync=None):
        self.root, self.lobby, self.game_factory = root, lobby, game_factory
        self.steam_name_loader = steam_name_loader
        self.map_sync = map_sync
        self.game = None
        self.room = None
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
        self.players = []
        self.closing = False
        self.copy_reset_handle = None
        root.title('TRIBES 3 • Community Starter')
        root.geometry('1030x800')
        root.minsize(850, 650)
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
        self.allow_bots = tk.BooleanVar(value=False)
        self.bot_count = tk.StringVar(value='2')
        self.retail_capture_point = tk.BooleanVar(value=True)
        self.live_status = tk.StringVar(value='Checking spectator support…')
        side = tk.Frame(root, bg='#0d1927', width=225)
        self.sidebar = side
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        self.label(side, 'TRIBES 3', 25, True, bg='#0d1927').pack(anchor='w', padx=24, pady=(36, 0))
        self.label(side, 'COMMUNITY STARTER', 9, color=ACCENT, bg='#0d1927').pack(anchor='w', padx=26, pady=(4, 32))
        self.lobbies_nav=self.button(side,'Lobbies',lambda:self.show_panel('lobbies'),False)
        self.lobbies_nav.pack(fill='x',padx=18,pady=(0,6))
        self.live_nav=self.button(side,'Live matches',lambda:self.show_panel('live'),False)
        self.live_nav.pack(fill='x',padx=18)
        if server_access is not None:
            from server_access import show_setup
            self.access_button = self.button(side, 'Set up server access', lambda: show_setup(self, server_access), False)
            self.access_button.pack(fill='x', padx=18, pady=(20, 0))
        self.label(side, 'Private playtest', 10, color=MUTED, bg='#0d1927').pack(side='bottom', anchor='w', padx=26, pady=24)
        tk.Label(side,textvariable=self.preparation,bg='#0d1927',fg=MUTED,font=('Segoe UI',10),
                 anchor='w',justify='left',wraplength=175).pack(side='bottom',anchor='w',padx=26,pady=(0,12))
        if self.map_sync is not None:
            self.map_status = tk.StringVar(value='')
            tk.Label(side,textvariable=self.map_status,bg='#0d1927',fg=MUTED,font=('Segoe UI',10),
                     anchor='w',justify='left',wraplength=175).pack(side='bottom',anchor='w',padx=26,pady=(0,12))
        main = tk.Frame(root, bg=BG)
        self.lobby_panel=main
        main.pack(side='left', fill='both', expand=True, padx=32, pady=28)
        self.label(main, 'Get your team together.', 27, True).pack(anchor='w')
        self.label(main, 'Create a lobby, choose teams, and pick a map.', 11, color=MUTED).pack(anchor='w', pady=(4, 18))
        entry = tk.Frame(main, bg=PANEL, padx=18, pady=14)
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
        self.join_button = self.button(entry,'Join lobby',self.join,False)
        self.join_button.grid(row=2,column=1,sticky='w',padx=(12,0))
        card = tk.Frame(main,bg=PANEL,padx=18,pady=14)
        card.pack(fill='both',expand=True,pady=(14,0))
        heading = tk.Frame(card,bg=PANEL)
        heading.pack(fill='x')
        self.copy_code_button = self.button(heading,'Copy lobby code',self.copy_lobby_code,False)
        self.copy_code_button.pack(side='right',padx=(12,0))
        tk.Label(heading,textvariable=self.room_heading,bg=PANEL,fg=TEXT,font=('Segoe UI',17,'bold'),anchor='w').pack(side='left',fill='x',expand=True)
        tk.Label(card,textvariable=self.phase,bg=PANEL,fg=MUTED,font=('Segoe UI',10),anchor='w').pack(fill='x',pady=(2,8))
        maprow = tk.Frame(card,bg=PANEL);maprow.pack(fill='x')
        self.label(maprow,'MAP',9,color=ACCENT,bg=PANEL).pack(side='left',padx=(0,12))
        self.map_options=options(LEGACY_MAPS)
        self.map_combo = ttk.Combobox(maprow,textvariable=self.map_name,values=tuple(item['label'] for item in self.map_options),state='disabled')
        self.map_combo.pack(side='left',fill='x',expand=True)
        self.map_combo.bind('<<ComboboxSelected>>',lambda e:self.choose_map())
        self.spectator_toggle=tk.Checkbutton(maprow,text='Allow spectators',variable=self.allow_spectators,
            command=self.toggle_spectators,bg=PANEL,fg=TEXT,selectcolor='#20374a',activebackground=PANEL,
            activeforeground=TEXT,font=('Segoe UI',9))
        roster_frame = tk.Frame(card,bg=PANEL)
        roster_frame.pack(fill='both',expand=True,pady=(14,4))
        self.rules_row = tk.Frame(card,bg=PANEL)
        check_style = dict(bg=PANEL,fg=TEXT,selectcolor='#20374a',activebackground=PANEL,
                           activeforeground=TEXT,font=('Segoe UI',9))
        self.flag_toggle = tk.Checkbutton(self.rules_row,text='Flag indicators',variable=self.flag_indicators,
            command=lambda:self.call_action('rules',flagIndicators=self.flag_indicators.get()),**check_style)
        self.flag_toggle.pack(side='left')
        self.bot_toggle = tk.Checkbutton(self.rules_row,text='Allow bots',variable=self.allow_bots,
            command=self.change_bots,**check_style)
        self.bot_toggle.pack(side='left',padx=(10,0))
        self.bot_spinner = ttk.Spinbox(self.rules_row,from_=1,to=MAX_LOBBY_BOTS,textvariable=self.bot_count,
                                       width=3,state='disabled',command=self.change_bots)
        self.bot_spinner.pack(side='left',padx=(2,10))
        self.capture_toggle = tk.Checkbutton(self.rules_row,text='Retail capture point',variable=self.retail_capture_point,
            command=lambda:self.call_action('rules',retailCapturePoint=self.retail_capture_point.get()),**check_style)
        self.capture_toggle.pack(side='left')
        self.roster = tk.Listbox(roster_frame,bg='#0b1a29',fg=TEXT,selectbackground='#31566c',font=('Segoe UI',11),relief='flat',height=8,exportselection=False)
        roster_scroll = ttk.Scrollbar(roster_frame,orient='vertical',command=self.roster.yview)
        self.roster.configure(yscrollcommand=roster_scroll.set)
        roster_scroll.pack(side='right',fill='y')
        self.roster.pack(side='left',fill='both',expand=True)
        teams = tk.Frame(card,bg=PANEL);teams.pack(side='bottom',before=roster_frame,fill='x')
        self.blue_button = self.button(teams,'Join blue',lambda:self.call_action('team',team='blue'),False);self.blue_button.pack(side='left',padx=(0,8))
        self.red_button = self.button(teams,'Join red',lambda:self.call_action('team',team='red'),False);self.red_button.pack(side='left',padx=(0,8))
        self.move_blue = self.button(teams,'Move selected blue',lambda:self.move('blue'),False);self.move_blue.pack(side='left',padx=(0,8))
        self.move_red = self.button(teams,'Move selected red',lambda:self.move('red'),False);self.move_red.pack(side='left')
        actions = tk.Frame(main,bg=BG);actions.pack(side='bottom',before=card,fill='x',pady=(14,0))
        self.start_button = self.button(actions,'Start match',lambda:self.call_action('start'));self.start_button.pack(side='left',padx=(0,8))
        self.game_button = self.button(actions,'Join game',self.join_game);self.game_button.pack(side='left',padx=(0,8))
        self.stop_button = self.button(actions,'Stop match',lambda:self.call_action('stop'),False);self.stop_button.pack(side='left',padx=(0,8))
        self.reset_button = self.button(actions,'New setup',lambda:self.call_action('reset'),False);self.reset_button.pack(side='left',padx=(0,8))
        self.leave_button = self.button(actions,'Leave',lambda:self.call_action('leave'),False);self.leave_button.pack(side='left')
        tk.Label(main,textvariable=self.status,bg=BG,fg=MUTED,font=('Segoe UI',10),anchor='w',wraplength=700).pack(side='bottom',before=actions,fill='x',pady=(12,0))
        self.live_panel=tk.Frame(root,bg=BG)
        self.label(self.live_panel,'Watch live matches.',27,True).pack(anchor='w')
        self.live_summary=self.label(self.live_panel,'Spectate a running community match in first person. In game: F5/F6 switch players; F7 restores first person.',
                   11,color=MUTED)
        self.live_summary.configure(wraplength=500,justify='left')
        self.live_summary.pack(anchor='w',pady=(4,18))
        live_card=tk.Frame(self.live_panel,bg=PANEL,padx=18,pady=18)
        live_card.pack(fill='both',expand=True)
        self.live_list=ttk.Treeview(live_card,columns=('match','map','players','spectators'),show='headings',height=10,selectmode='browse',style='Live.Treeview')
        for key,title,width in (('match','Match',90),('map','Map',220),('players','Assigned players',115),('spectators','Spectator seats',115)):
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
        tk.Label(self.live_panel,textvariable=self.live_status,bg=BG,fg=MUTED,font=('Segoe UI',10),
                 anchor='w',justify='left',wraplength=650).pack(fill='x',pady=(12,0))
        self.render_live_controls()
        self.render(None)
        if steam_name_loader:
            self.run_async(steam_name_loader, self.set_steam_name)
        else:
            self.run_async(self.lobby.capabilities, self.set_capabilities)
        self.poll_handle=root.after(150,self.poll)
        self.refresh_handle=root.after(2000,self.refresh)
        self.live_refresh_handle=root.after(3000,self.live_tick)

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
        if not self.closing: self.poll_handle=self.root.after(150,self.poll)

    def set_capabilities(self, caps):
        self.caps = caps
        self.capabilities_loaded = True
        if self.map_sync is not None:
            self.map_sync.start(caps.get('mapFileSync'))
        self.status.set('Community service connected.')
        self.render(self.room)
        self.render_live_controls()
        if self.room is None and caps.get('lobbyResumeEnabled') is True:
            self.run_async(self.lobby.resume, self.render)
        elif self.current_panel=='live':
            self.refresh_live_matches()

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
        in_room = room is not None
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
        for widget in (self.name_entry,self.code_entry,self.create_button,self.join_button): widget.configure(state='disabled' if in_room or self.controls_busy else 'normal')
        if self.steam_name_loader and not in_room and not self.controls_busy:
            self.name_entry.configure(state='readonly', readonlybackground='#20374a')
        self.room_heading.set('Lobby  '+room['code'] if in_room else 'Not in a lobby')
        self.phase.set(match_phase_text(room))
        available=room.get('availableMaps') if in_room else self.caps.get('maps')
        if available is None: available=options(LEGACY_MAPS)
        try:
            dynamic = self.caps.get('mapFileSync') == CATALOG_VERSION
            labels = read_options(available, dynamic=dynamic)
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
        self.map_combo.configure(values=tuple(item['label'] for item in available),height=min(18,len(available)),state='readonly' if setup and leader else 'disabled')
        if in_room:
            if self.pending_map and self.pending_map[1] not in labels:
                self.pending_map = None
            self.map_name.set(labels[self.pending_map[1] if self.pending_map else room['map']])
        self.render_match_rules(room, setup and leader and not self.controls_busy and self.pending_map is None)
        selected = self.roster.curselection()
        selected_id = self.players[selected[0]]['id'] if selected and selected[0] < len(self.players) else None
        scroll_position = self.roster.yview()[0]
        self.players = room['players'] if in_room else []
        self.roster.delete(0,tk.END)
        for index,player in enumerate(self.players):
            self.roster.insert(tk.END, (player['team'] or 'unassigned').upper()+'    '+player['name']+('  • leader' if player['leader'] else '')+('  • you' if player['id']==room['playerId'] else ''))
            if player['id'] == selected_id:
                self.roster.selection_set(index)
                self.roster.activate(index)
        if in_room:
            self.roster.yview_moveto(scroll_position)
        for widget in (self.blue_button,self.red_button): widget.configure(state='normal' if setup and not self.controls_busy else 'disabled')
        for widget in (self.move_blue,self.move_red): widget.configure(state='normal' if setup and leader and not self.controls_busy else 'disabled')
        self.start_button.configure(state='normal' if setup and leader and not self.controls_busy and self.pending_map is None and self.caps.get('matchStartEnabled') else 'disabled')
        self.game_button.configure(state='normal' if in_room and phase=='ready' and not self.controls_busy and self.pending_map is None and self.caps.get('gameClientReady') else 'disabled')
        self.stop_button.configure(state='normal' if leader and phase in ('starting','ready') else 'disabled')
        self.reset_button.configure(state='normal' if leader and phase in ('stopped','ended','failed') else 'disabled')
        self.leave_button.configure(state='normal' if in_room and not self.controls_busy else 'disabled')
        # Preparation has no match endpoint or player profile. Start it as soon
        # as the service confirms support, while the player is choosing a lobby.
        if self.capabilities_loaded and self.caps.get('gameClientReady'):
            try:
                if not self.game:self.game=self.game_factory(self.lobby)
                prepare=getattr(self.game,'prepare',None)
                if prepare:prepare()
            except Exception as exc:
                self.preparation.set('Game preparation: '+str(exc))

    def create(self):
        if self.steam_name_loader:
            self.enter_with_steam(lambda name:self.lobby.create(name))
        else:
            name = self.name.get()
            self.run_async(lambda:self.lobby.create(name),self.render)

    def join(self):
        code, name = self.code.get().strip().upper(), self.name.get()
        if self.steam_name_loader:
            self.enter_with_steam(lambda name:self.lobby.join(code,name))
        else:
            self.run_async(lambda:self.lobby.join(code,name),self.render)

    def enter_with_steam(self, operation):
        def work():
            name=self.steam_name_loader()
            return name,operation(name)
        def entered(value):
            name,room=value
            self.name.set(name)
            self.render(room)
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

    def move(self,team):
        selection = self.roster.curselection()
        if not selection: self.status.set('Select a player first.');return
        self.call_action('team',team=team,playerId=self.players[selection[0]]['id'])

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
            self.rules_row.pack_forget()
            return
        if not self.rules_row.winfo_manager():
            self.rules_row.pack(fill='x',before=self.roster.master,pady=(6,0))
        rules = room.get('rules', DEFAULT_LOBBY_RULES) if room else DEFAULT_LOBBY_RULES
        self.flag_indicators.set(rules['flagIndicators'])
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
        panel=self.live_panel if name=='live'else self.lobby_panel
        panel.pack(side='left',fill='both',expand=True,padx=32,pady=28)
        self.render_live_controls()
        if name=='live':self.refresh_live_matches()

    def render_live_controls(self):
        supported=self.caps.get('spectateEnabled')is True
        selected=self.live_list.selection()
        target=self.live_targets.get(selected[0])if selected else None
        active=self.game_status not in ('idle','stopped','finished','failed')
        can_watch=supported and target is not None and target.get('canSpectate')is True and not active and self.watch_id is None
        self.spectate_button.configure(state='normal'if can_watch and not self.controls_busy else'disabled')
        self.stop_watch_button.configure(state='normal'if self.watch_id is not None and not self.controls_busy else'disabled')
        self.live_refresh_button.configure(state='normal'if supported and not self.controls_busy else'disabled')
        if not supported and self.capabilities_loaded:self.live_status.set('Spectating is unavailable on this server version.')

    def render_live_matches(self,matches):
        selected=self.live_list.selection()
        previous=selected[0]if selected else None
        scroll=self.live_list.yview()[0]
        self.live_targets={item['id']:item for item in matches}
        children=self.live_list.get_children()
        if children:self.live_list.delete(*children)
        for item in matches:
            self.live_list.insert('',tk.END,iid=item['id'],values=(
                'Match '+item['id'][:6].upper(),item['label'],
                str(item['playerCount'])+' / '+str(item['playerCapacity']),
                str(item['spectatorCount'])+' / '+str(item['spectatorCapacity'])))
        if previous in self.live_targets:self.live_list.selection_set(previous)
        self.live_list.yview_moveto(scroll)
        if self.watch_id is None:
            self.live_status.set('Select a match to watch.'if matches else'No spectator-enabled matches are live right now.')
        self.render_live_controls()

    def refresh_live_matches(self, *, background=False):
        if self.controls_busy or self.closing or self.caps.get('spectateEnabled')is not True:return
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
    Desktop(root,lobby,game_factory,steam_name_loader=steam_name_loader,server_access=access,map_sync=map_sync)
    if on_ready is not None:
        root.update_idletasks()
        on_ready()
    root.mainloop()


if __name__ == '__main__':
    main()
