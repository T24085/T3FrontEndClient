import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from starter_update import INDEX, sha
from tools import windows_starter_release as release


def file_row(name, data):
    return {'path': name, 'bytes': len(data), 'sha256': sha(data)}


class WindowsStarterReleaseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)
        self.base = self.work / 'full-r44.zip'
        self.output = self.work / 'full-r94.zip'
        self.original = b'old handler'
        self.current = b'current handler'
        self.managed = 'map_sync_contract.py'
        self.index = {'revision': 94, 'files': {self.managed: {
            'bytes': len(self.current), 'sha256': sha(self.current)}}}

    def write_package(self, *, revision=44, handler=None, map_count=1):
        handler = self.original if handler is None else handler
        members = {self.managed: handler,
                   'python/pythonw.exe': b'python',
                   'clan_wars_windows.pyw': b'windows entry'}
        members.update({f'content/Community/Test/Asset{i}.uasset': b'map' for i in range(map_count)})
        manifest = {'direct_host_contract': 'direct', 'starter_update_revision': revision,
                    'starter_update_files': [self.managed], 'map_runtime': {'Test': []},
                    'files': [file_row(name, data) for name, data in members.items()]}
        with ZipFile(self.base, 'w') as archive:
            archive.writestr(release.OPENER, b'launcher')
            archive.writestr(release.INVITATION, b'player invitation')
            archive.writestr(release.MANIFEST, json.dumps(manifest))
            for name, data in members.items():
                archive.writestr(release.CLIENT + name, data)
        return manifest

    def fetch(self, name, bound):
        if name == INDEX:
            return b'test index'
        self.assertEqual(name, f'starter-file-{sha(self.current)}.bin')
        self.assertEqual(bound, len(self.current))
        return self.current

    def test_r44_is_rejected_against_live_r94(self):
        self.write_package()
        with ZipFile(self.base) as archive, self.assertRaisesRegex(ValueError, 'bundles r44.*r94'):
            release.verify_index(archive, release.manifest_for(archive), self.index)

    def test_r94_label_does_not_pass_when_bundled_file_is_stale(self):
        self.write_package(revision=94)
        with ZipFile(self.base) as archive, self.assertRaisesRegex(ValueError, self.managed):
            release.verify_index(archive, release.manifest_for(archive), self.index)

    def test_reissue_embeds_r94_and_preserves_over_ten_thousand_map_files(self):
        manifest = self.write_package(map_count=10_001)
        with patch.object(release, 'live_fetch', return_value=self.fetch), \
                patch.object(release, 'live_index', return_value=self.index):
            revision = release.reissue(self.base, release.archive_sha(self.base), self.output)

        self.assertEqual(revision, 94)
        with ZipFile(self.output) as archive:
            rebuilt = release.manifest_for(archive)
            self.assertEqual(release.verify_index(archive, rebuilt, self.index), 94)
            self.assertEqual(archive.read(release.OPENER), b'launcher')
            self.assertEqual(archive.read(release.INVITATION), b'player invitation')
            maps = [row for row in rebuilt['files'] if row['path'].startswith('content/')]
            self.assertEqual(maps, [row for row in manifest['files'] if row['path'].startswith('content/')])
            self.assertEqual(archive.read(release.CLIENT + 'content/Community/Test/Asset10000.uasset'), b'map')

    def test_feed_change_during_build_blocks_the_output(self):
        self.write_package()
        advanced = dict(self.index, revision=95)
        with patch.object(release, 'live_fetch', return_value=self.fetch), \
                patch.object(release, 'live_index', side_effect=[self.index, advanced]), \
                self.assertRaisesRegex(ValueError, 'bundles r94.*r95'):
            release.reissue(self.base, release.archive_sha(self.base), self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
