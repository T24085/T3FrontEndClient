import sys
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent/'experimental/direct-hosting/src'))
from direct_client import RankedPugPanel
from desktop_launcher import Desktop


class RankedLauncherTests(unittest.TestCase):
    def test_play_queue_ballot_loading_and_profile_controls(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.withdraw()
        navigated, requests = [], []
        desktop = SimpleNamespace(root=root, closing=False, current_panel='pug', game_status='idle',
                                  controls_busy=False, entry_panel=tk.Frame(root), sidebar=tk.Frame(root),
                                  show_panel=navigated.append)
        desktop.label = lambda *args, **kw: Desktop.label(desktop, *args, **kw)
        desktop.button = lambda *args, **kw: Desktop.button(desktop, *args, **kw)
        panel = RankedPugPanel(tk, desktop, SimpleNamespace(map_label=lambda key: key))
        panel.action = lambda action, **params: requests.append((action, params))
        desktop.entry_panel.winfo_children()[0].invoke()
        desktop.sidebar.winfo_children()[0].invoke()
        self.assertEqual(navigated, ['pug', 'stats'])
        desktop.player_name_for_action = lambda: 'Test Player'
        panel.join.invoke()
        self.assertEqual(requests.pop(), ('join', {'name': 'Test Player'}))
        room = dict(id='pug', phase='voting', seconds=20, team='red', blue=['Blue']*7, red=['Red']*7,
                    options=[dict(id=m, label=m, votes=0) for m in ('Katabatic', 'Torment', 'Hollow')])
        panel.state = {'room': room}
        panel.render()
        self.assertEqual(panel.teams['red'].cget('text').splitlines(), ['Red']*7)
        panel.votes[1].invoke()
        self.assertEqual(requests.pop(), ('vote', {'room': 'pug', 'map': 'Torment'}))
        self.assertEqual(panel.launch.cget('state'), 'disabled')
        room.update(phase='loading', map='Torment', game={'matchId': 'a'*32},
                    progress='Waiting for players — 13/14 players loaded')
        panel.render()
        self.assertEqual(panel.launch.cget('state'), 'normal')
        self.assertIn('13/14', panel.status.get())
        row = dict(id=45, rank=2, name='Test Player', mu=32.4, sigma=4.3, wins=2, losses=1, draws=0,
                   stats={'flagGrabs': 3, 'flagHeldSeconds': 130, 'native.Kills': 5, 'native.Stat.Kills': 99,
                          'native.Deaths': 2, 'native.Assists': 4, 'native.Captures': 1, 'native.Returns': 6,
                          'native.Bot_Kills': 8})
        legacy = dict(row, id=46, stats={'native.Stat.Kills': 7, 'native.STAT_Assists': 9})
        panel.render_stats({'players': [row, legacy], 'profile': row, 'hasMore': False})
        self.assertIn('32.40', panel.profile.get())
        visible = {'kills': '5', 'deaths': '2', 'assists': '4', 'captures': '1', 'returns': '6',
                   'grabs': '3', 'held': '2:10'}
        self.assertEqual({name: panel.table.set('45', name) for name in visible}, visible)
        self.assertEqual(panel.table.set('46', 'kills'), '7')
        self.assertEqual(panel.table.set('46', 'assists'), '9')
        self.assertEqual(panel.table.set('46', 'returns'), '0')
        detail = [(panel.detail.set(item, 'stat'), panel.detail.set(item, 'total'))
                  for item in panel.detail.get_children()]
        self.assertEqual(detail, [(panel.table.heading(name, 'text'), value) for name, value in visible.items()]
                         + [('Bot_Kills', '8')])


if __name__ == '__main__':
    unittest.main()
