"""Regress the private Weapons section without contacting a host."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).with_name('src')))
from direct_client import ArmorPanel, load_weapon_library


class WeaponLibraryTest(unittest.TestCase):
    def test_catalog_rejects_paths_outside_the_model_directory(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            document = {'format': 1, 'weapons': {'Spinfusor': {'First person': {'Base': '../model.t3m'}}}}
            (directory/'catalog.json').write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'Invalid weapon model'):
                load_weapon_library(directory)

    @unittest.skipUnless(os.name == 'nt', 'The model viewport uses Windows OpenGL.')
    def test_armor_switches_between_suits_and_local_weapon_models(self):
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            desktop = Mock(root=root, sidebar=tk.Frame(root))
            desktop.label.side_effect = lambda parent, label, *_args, **_kwargs: tk.Label(parent, text=label)
            desktop.button.side_effect = lambda parent, label, command, *_args: tk.Button(parent, text=label, command=command)
            with TemporaryDirectory() as folder:
                directory = Path(folder)
                document = {'format': 1, 'weapons': {'Spinfusor': {
                    'First person': {'Base': '0123456789abcdef.t3m', 'Blood Eagle': 'abcdef0123456789.t3m'},
                    'Third person': {'Base': None},
                }}}
                (directory/'catalog.json').write_text(json.dumps(document))
                lobby = Mock()
                armor = ArmorPanel(tk, desktop, lobby, weapon_directory=directory)
                armor.panel.pack(expand=True, fill='both')
                with patch('armor_viewport.ArmorViewport') as viewport, patch('armor_viewport.read_model') as read:
                    read.return_value = Mock(texture=None)
                    armor.show_section(True)
                    weapons = armor.weapons_panel
                    self.assertFalse(armor.suits_panel.winfo_manager())
                    self.assertEqual(weapons.fields[0].get(), 'Spinfusor')
                    read.assert_called_once_with(directory/'models/0123456789abcdef.t3m')
                    weapons.fields[2].set('Blood Eagle')
                    weapons.show_model()
                    self.assertEqual(read.call_args.args[0], directory/'models/abcdef0123456789.t3m')
                    viewport.return_value.show.assert_called_with(read.return_value)
                    weapons.fields[1].set('Third person')
                    weapons.choose_view()
                    self.assertIn('unavailable', weapons.notice.cget('text'))
                    self.assertFalse(weapons.preview.winfo_manager())
                    lobby.assert_not_called()
                    lobby.armor_suits.assert_not_called()
                    with patch.object(armor, 'submit') as submit:
                        armor.show_section(False)
                        submit.assert_called_once_with('load')
                    self.assertFalse(weapons.panel.winfo_manager())
                    self.assertEqual(armor.suits_panel.winfo_manager(), 'pack')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
