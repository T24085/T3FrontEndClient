import unittest
from pathlib import Path
from unittest.mock import patch
import startup_paths as paths


class WorkspaceTests(unittest.TestCase):
    def test_external_library_defaults_to_its_own_drive(self):
        with patch.object(paths, 'local_directory', return_value=Path('C:/Users/test/AppData/Local/Tribes3CommunityStarter')), patch.object(paths, 'local_filesystem', return_value='NTFS'), patch.object(Path, 'is_dir', return_value=True):
            game, workspace = paths.installation_options('D:/SteamLibrary/steamapps/common/TRIBES 3 Rivals')
            self.assertEqual(workspace.drive.lower(), 'd:')
            self.assertNotEqual(workspace, Path(game))
            self.assertNotIn(Path(game), workspace.parents)

    def test_exfat_library_keeps_ntfs_local_cache(self):
        local = Path('C:/Users/test/AppData/Local/Tribes3CommunityStarter')
        with patch.object(paths, 'local_directory', return_value=local), patch.object(paths, 'local_filesystem', return_value='exFAT'), patch.object(Path, 'is_dir', return_value=True):
            self.assertEqual(paths.session_workspace(game_directory='D:/Games/Tribes'), local/'sessions')

    def test_system_drive_keeps_existing_local_cache(self):
        local = Path('C:/Users/test/AppData/Local/Tribes3CommunityStarter')
        with patch.object(paths, 'local_directory', return_value=local):
            self.assertEqual(paths.session_workspace(game_directory='C:/Games/Tribes'), local/'sessions')

    def test_explicit_workspace_is_preserved(self):
        self.assertEqual(paths.session_workspace('E:/PrivateSessions', 'D:/Games/Tribes'), Path('E:/PrivateSessions'))

    def test_saved_preferences_are_preserved(self):
        preferences = {'game_directory':'D:/Games/Tribes', 'workspace':'E:/ExistingSessions'}
        with patch.object(paths, 'installation_preferences', return_value=preferences):
            self.assertEqual(paths.installation_options(), ('D:/Games/Tribes', Path('E:/ExistingSessions')))


if __name__ == '__main__':
    unittest.main()
