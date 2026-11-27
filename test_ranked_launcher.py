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
                                  controls_busy=False, play_actions=tk.Frame(root), sidebar=tk.Frame(root),
                                  show_panel=navigated.append)
        desktop.label = lambda *args, **kw: Desktop.label(desktop, *args, **kw)
        desktop.button = lambda *args, **kw: Desktop.button(desktop, *args, **kw)
        panel = RankedPugPanel(tk, desktop, SimpleNamespace(map_label=lambda key: key))
        panel.action = lambda action, **params: requests.append((action, params))
        desktop.play_actions.winfo_children()[0].invoke()
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
        row = dict(id=(1 << 52) + 45, rank=2, name='Test Player', mu=32.4, sigma=4.3, wins=2, losses=1, draws=0,
                   stats={'flagGrabs': 3, 'flagHeldSeconds': 130, 'native.Stat.Kills': 5})
        panel.render_stats({'players': [row], 'profile': row, 'hasMore': False})
        self.assertIn('32.40', panel.profile.get())
        self.assertEqual(panel.table.set(str(row['id']), 'held'), '2:10')
        self.assertTrue(any(panel.detail.set(item, 'stat') == 'Kills' for item in panel.detail.get_children()))


if __name__ == '__main__':
    unittest.main()
