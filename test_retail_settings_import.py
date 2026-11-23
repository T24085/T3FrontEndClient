"""Exercise the retail settings import with private Windows profile fixtures."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import player_profile as profiles


class RetailSettingsImportTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        local = Path(folder.name)
        self.root = local / 'Tribes3CommunityStarter/player-settings'
        self.retail = local / 'Topaz' / profiles.CONFIG_DIRECTORY
        self.profile = self.root / 'profile' / profiles.CONFIG_DIRECTORY
        self.retail.mkdir(parents=True)
        self.game = self.enterContext(patch('client_support.running_image', return_value=False))
        self.retail_input = (
            '[Unrelated]\r\nCustomActionKeyMappings=Ignore\r\n'
            '[/Script/Valhalla.ValPlayerInput]\r\n!CustomActionKeyMappings=ClearArray\r\n'
            '+CustomActionKeyMappings=(Ski,LeftShift)\r\n'
            '+CustomActionKeyMappings=(Jet,RightMouseButton)\r\n'
            'SavedSettingsConfig=(Sensitivity=0.8)\r\n'
            'SpinfusorLateralInheritance=0.67\r\nOtherSavedInputOption=True\r\n'
        ).encode()
        self.retail_game = (
            '[ScalabilityGroups]\nsg.TextureQuality=2\n'
            '[/Script/Valhalla.ValGameUserSettings]\nDesiredFOV=105\nVolume=0.5\n'
            'SpinfusorForwardInheritance=0.73\nHonorfusorLateralInheritance=0.91\n'
            '[/Script/Engine.GameUserSettings]\nbUseVSync=True\n'
            '[Other]\nOnlyInRetail=Ignore\n'
        ).encode()
        (self.retail / 'Input.ini').write_bytes(self.retail_input)
        (self.retail / 'GameUserSettings.ini').write_bytes(self.retail_game)

    def test_first_launch_offer_is_read_only_and_requires_saved_retail_settings(self):
        self.assertIsNotNone(profiles.windows_retail_import_offer(self.root))
        self.assertFalse(self.root.exists())
        self.game.return_value = True
        with self.assertRaises(profiles.ProfileBusy):
            profiles.windows_retail_import_offer(self.root)
        self.game.return_value = False
        (self.retail/'Input.ini').write_text('[Other]\nDefault=1\n', encoding='utf-8')
        (self.retail/'GameUserSettings.ini').unlink()
        self.assertIsNone(profiles.windows_retail_import_offer(self.root))

    def test_automatic_import_checks_profile_again_before_replacing_saved_settings(self):
        self.assertIsNotNone(profiles.windows_retail_import_offer(self.root))
        originals = self.existing()
        self.assertIsNone(profiles.windows_retail_import_offer(self.root))
        with self.assertRaisesRegex(profiles.ProfileError, 'already in use'):
            profiles.import_retail_settings(root=self.root, first_launch=True)
        for name, raw in originals.items():
            self.assertEqual((self.profile/name).read_bytes(), raw)
        result = profiles.import_retail_settings(root=self.root)
        self.assertIn('Input.ini', result)

    def test_prompt_state_persists_without_changing_game_files(self):
        self.assertTrue(profiles.retail_import_prompt_pending(self.root))
        for state in ('dismissed', 'done'):
            profiles.remember_retail_import_prompt(self.root, state)
            self.assertFalse(profiles.retail_import_prompt_pending(self.root))
        self.assertFalse(self.profile.exists())

    def existing(self):
        self.profile.mkdir(parents=True)
        retail_section = profiles.RETAIL_INPUT_SECTION
        game_section = profiles.RETAIL_GAME_SECTIONS[0]
        old_input = (f'[{retail_section}]; custom\r\n+CustomActionKeyMappings=(Old,Ski)\r\n'
                     'SavedSettingsConfig=Old\r\nCommunityKey=Keep\r\n'
                     f'[{retail_section.lower()}]\r\n.CustomActionKeyMappings=(Old,Jet)\r\n'
                     '[Other]\r\nCustomActionKeyMappings=Keep\r\n')
        old_game = f'[{game_section}]\r\nDesiredFOV=90\r\n[Other]\r\nUnicode=Déjà\r\n'
        originals = {'Input.ini': old_input.encode('utf-8-sig'),
                     'GameUserSettings.ini': old_game.encode('utf-16'),
                     'Engine.ini': b'[Engine]\r\nKeep=1\r\n'}
        for name, raw in originals.items():
            (self.profile / name).write_bytes(raw)
        return originals

    def test_merges_only_requested_sections_and_backs_up_changed_files(self):
        original = self.existing()
        result = profiles.import_retail_settings(root=self.root)
        self.assertEqual(result, ('Input.ini', 'GameUserSettings.ini'))
        imported_input = (self.profile / 'Input.ini').read_bytes()
        self.assertTrue(imported_input.startswith(b'\xef\xbb\xbf'))
        text = imported_input.decode('utf-8-sig')
        self.assertIn('!CustomActionKeyMappings=ClearArray\r\n'
                      '+CustomActionKeyMappings=(Ski,LeftShift)\r\n'
                      '+CustomActionKeyMappings=(Jet,RightMouseButton)\r\n', text)
        self.assertIn('SavedSettingsConfig=(Sensitivity=0.8)\r\n', text)
        self.assertIn('CommunityKey=Keep\r\n', text)
        self.assertIn('SpinfusorLateralInheritance=0.67\r\n', text)
        self.assertIn('OtherSavedInputOption=True\r\n', text)
        self.assertIn('[Other]\r\nCustomActionKeyMappings=Keep\r\n', text)
        self.assertNotIn('Ignore', text)
        self.assertNotIn('Old', text)
        game = (self.profile / 'GameUserSettings.ini').read_bytes().decode('utf-16')
        self.assertIn('DesiredFOV=105\r\nVolume=0.5\r\n', game)
        self.assertIn('[ScalabilityGroups]\r\nsg.TextureQuality=2\r\n', game)
        self.assertIn('SpinfusorForwardInheritance=0.73\r\nHonorfusorLateralInheritance=0.91\r\n', game)
        self.assertIn('[Other]\r\nUnicode=Déjà\r\n', game)
        self.assertIn('[/Script/Engine.GameUserSettings]\r\nbUseVSync=True\r\n', game)
        self.assertNotIn('OnlyInRetail', game)
        self.assertEqual((self.profile / 'Engine.ini').read_bytes(), original['Engine.ini'])
        backups = list((self.root / 'backups').glob('*.bak'))
        self.assertEqual(len(backups), 2)
        for backup in backups:
            self.assertEqual(backup.read_bytes(), original[backup.name.rsplit('.', 2)[0]])
        self.assertEqual((self.retail / 'Input.ini').read_bytes(), self.retail_input)
        self.assertEqual((self.retail / 'GameUserSettings.ini').read_bytes(), self.retail_game)
        self.assertEqual(profiles.import_retail_settings(root=self.root), ())
        self.assertEqual(len(list((self.root / 'backups').glob('*.bak'))), 2)

    def test_first_run_preserves_missing_settings_and_never_creates_engine_config(self):
        (self.retail / 'GameUserSettings.ini').unlink()
        self.assertEqual(profiles.import_retail_settings(root=self.root), ('Input.ini',))
        self.assertEqual({path.name for path in self.profile.iterdir()}, {'Input.ini'})
        self.assertFalse((self.root / 'backups').exists())

    def test_refuses_running_game_or_another_starter_holding_the_native_lock(self):
        self.game.return_value = True
        with self.assertRaisesRegex(profiles.ProfileBusy, 'Close TRIBES 3'):
            profiles.import_retail_settings(root=self.root)
        self.assertFalse(self.root.exists())
        self.game.return_value = False
        with profiles.ProfileSession(mode='', root=self.root):
            with self.assertRaisesRegex(profiles.ProfileBusy, 'community game'):
                profiles.import_retail_settings(root=self.root)
        self.assertFalse((self.profile / 'Input.ini').exists())

    def test_malformed_retail_and_second_write_failure_preserve_originals(self):
        original = self.existing()
        settings = self.retail / 'GameUserSettings.ini'
        settings.write_bytes(b'invalid')
        with self.assertRaises(profiles.ProfileError):
            profiles.import_retail_settings(root=self.root)
        settings.write_bytes(self.retail_game)
        atomic = profiles._atomic

        def fail_second(path, raw):
            if path.name == 'GameUserSettings.ini':
                raise OSError('fixture could not publish')
            atomic(path, raw)

        with patch.object(profiles, '_atomic', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'fixture could not publish'):
                profiles.import_retail_settings(root=self.root)
        for name, raw in original.items():
            self.assertEqual((self.profile / name).read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
