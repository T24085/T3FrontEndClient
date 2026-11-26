"""Lobby boundary mutator controls (#97)."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from boundary_controls import (FIELDS, BoundaryDialog, default_label, mode_selection, mode_values,
                               override_from_fields, summary, with_mode)

T1 = {'mode': 'flag_only', 'warn_players': True, 'flag_rule': 'return_after', 'flag_return_delay_s': 5}


class LogicTests(unittest.TestCase):
    def test_summary_names_the_rules(self):
        self.assertEqual(summary(T1), 'Flag-only · warn · flag home after 5 s')
        self.assertEqual(summary(None), "the map's own rules")
        self.assertIn('vehicles destroyed', summary({'mode': 'damage', 'grace_s': 0, 'vehicles': 'destroy'}))

    def test_mode_choice_keeps_other_overrides(self):
        values = mode_values(T1)
        self.assertTrue(values[0].startswith('Map default (Flag-only'))
        self.assertEqual(mode_selection(T1, None), values[0])
        override = with_mode({'vehicles': 'destroy'}, values.index('Block players and flag'))
        self.assertEqual(override, {'vehicles': 'destroy', 'mode': 'block'})
        self.assertEqual(with_mode(override, 0), {'vehicles': 'destroy'})
        self.assertIsNone(with_mode({'mode': 'block'}, 0))

    def test_dialog_fields_become_a_validated_override(self):
        texts = {key: default_label(key, T1) for key, *_ in FIELDS}
        self.assertIsNone(override_from_fields(texts, T1))
        texts.update(flag_return_delay_s='10', vehicles='Destroy', grace_s='2.5')
        self.assertEqual(override_from_fields(texts, T1), {'flag_return_delay_s': 10, 'grace_s': 2.5, 'vehicles': 'destroy'})
        texts.update(grace_s='99')
        with self.assertRaises(ValueError):
            override_from_fields(texts, T1)
        # Without a map delay, choosing "return home after a delay" needs a delay too.
        bare = {key: default_label(key, None) for key, *_ in FIELDS}
        bare['flag_rule'] = 'Return home after a delay'
        with self.assertRaisesRegex(ValueError, 'delay'):
            override_from_fields(bare, None)


class TkTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f'No display for Tk: {error}')
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass  # The launcher's close() already destroyed it.

    def test_dialog_applies_and_resets(self):
        applied = []
        dialog = BoundaryDialog(self.root, T1, {'vehicles': 'destroy'}, applied.append)
        self.assertEqual(dialog.fields['vehicles'].get(), 'Destroy')
        self.assertEqual(dialog.fields['mode'].get(), 'Map default (Flag-only)')
        dialog.fields['grace_s'].set('4')
        dialog.submit()
        self.assertEqual(applied, [{'grace_s': 4, 'vehicles': 'destroy'}])
        dialog = BoundaryDialog(self.root, T1, {'vehicles': 'destroy'}, applied.append)
        dialog.reset()
        dialog.submit()
        self.assertIsNone(applied[-1])
        dialog = BoundaryDialog(self.root, T1, None, applied.append)
        dialog.fields['damage_per_s'].set('5')
        dialog.submit()
        self.assertIn('between', dialog.error.get())
        dialog.window.destroy()

    def test_launcher_row_sends_mode_and_saves_rule_sets(self):
        from desktop_launcher import Desktop
        from test_desktop_launcher import FakeGame, FakeLobby

        lobby = FakeLobby()
        app = Desktop(self.root, lobby, lambda _: FakeGame())
        try:
            deadline = time.monotonic() + 2
            while app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            app.render(lobby.room)
            self.assertFalse(app.boundary_row.winfo_manager())  # Older servers send no boundaryDefault.
            lobby.room.update(boundaryDefault=T1, boundary=None)
            app.render(lobby.room)
            self.assertTrue(app.boundary_row.winfo_manager())
            self.assertEqual(app.boundary_text.get(), summary(T1))
            with patch.object(app, 'call_action') as call:
                app.boundary_choice.current(2)  # Block players and flag
                app.change_boundary()
                call.assert_called_once_with('rules', boundary={'mode': 'block'})
            lobby.room.update(boundary={'mode': 'block'})
            app.render(lobby.room)
            self.assertTrue(app.boundary_text.get().startswith('Changed: Block players and flag'))
            with TemporaryDirectory() as folder:
                path = Path(folder) / 'Boundary.json'
                with patch('desktop_launcher.filedialog.asksaveasfilename', return_value=str(path)):
                    app.save_rule_preset()
                self.assertEqual(json.loads(path.read_bytes())['boundary'], {'mode': 'block'})
        finally:
            app.close()
            app.close_worker.join(2)


if __name__ == '__main__':
    unittest.main()
