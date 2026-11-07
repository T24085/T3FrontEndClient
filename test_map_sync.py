import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from map_sync import MapSync, load_overlay, overlay
from map_sync_contract import map_catalog

LEVEL = 'content/Maps/Community/Stonehenge/Arena_Stonehenge_P'
ASSET = 'content/Community/Stonehenge/Fixture.uasset'
OLD = 'content/Community/Stonehenge/Removed.uexp'
NEW = 'content/Community/Stonehenge/New.uexp'


def row(name, data):
    return {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class MapSyncTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bundled = {'community_maps': ['Stonehenge'], 'map_runtime': {'Stonehenge': []},
                        'files': [row('base-game-manifest.json', b'game'), row(LEVEL + '.umap', b'map'),
                                  row(LEVEL + '.uexp', b'export'), row(ASSET, b'old'), row(OLD, b'move')]}
        self.manifest = self.root / 'package-manifest.json'
        self.manifest.write_text(json.dumps(self.bundled))
        self.remote = self.remote_for([*self.bundled['files'][1:3], row(ASSET, b'new'), row(NEW, b'move')])
        self.sync = MapSync(None, self.root, self.root)
        self.sync._inventory = lambda: self.remote

    def remote_for(self, rows):
        catalog = map_catalog(dict(self.bundled, files=[self.bundled['files'][0], *rows]))
        return {'format': 1, 'maps': catalog, 'shared_content': {}, 'files': rows}

    def test_matching_package_checks_metadata_without_downloading(self):
        self.remote = self.remote_for(self.bundled['files'][1:])
        with patch.object(self.sync, '_download') as download:
            self.assertEqual(self.sync.refresh(), (None, self.remote['maps']))
        download.assert_not_called()
        self.assertFalse((self.root / 'map-downloads').exists())

    def test_join_fetches_changed_revision_and_next_start_reuses_it(self):
        fingerprint = self.remote['maps']['Stonehenge']
        self.sync.available = True
        def fetch(entry, target):
            self.assertEqual(entry['path'], ASSET)
            self.sync._write_verified(BytesIO(gzip.compress(b'new')), target, entry['sha256'], entry['bytes'])
        with patch.object(self.sync, '_download', side_effect=fetch) as download:
            revision = self.sync.revision_for('Stonehenge', fingerprint)
            download.assert_called_once()
        entries, catalog = load_overlay(self.root, revision, self.bundled)
        self.assertEqual(catalog['Stonehenge'], fingerprint)
        paths = {item['path']: (bundled, download) for item, bundled, download in entries}
        self.assertNotIn(OLD, paths)
        self.assertEqual(paths[NEW], (OLD, None))
        self.assertEqual(paths[ASSET][1].read_bytes(), b'new')
        self.assertEqual(json.loads(self.manifest.read_text()), self.bundled)
        restarted = MapSync(None, self.root, self.root)
        restarted._inventory = self.sync._inventory
        with patch.object(restarted, '_download') as download:
            self.assertEqual(restarted.refresh(), (revision, catalog))
        download.assert_not_called()

    def test_bad_gzip_hash_or_size_cannot_publish_revision(self):
        bad_payloads = (gzip.compress(b'bad'), gzip.compress(b'new extra'), gzip.compress(b'new')[:-4])
        for raw in bad_payloads:
            with self.subTest(payload=raw), patch.object(self.sync, '_download', side_effect=lambda entry, target:
                    self.sync._write_verified(BytesIO(raw), target, entry['sha256'], entry['bytes'])):
                with self.assertRaisesRegex(RuntimeError, 'Map update failed'):
                    self.sync.refresh()
                self.assertEqual(list((self.root / 'map-downloads').iterdir()), [])

    def test_non_map_file_and_mismatched_fingerprint_rejected_before_download(self):
        with self.assertRaisesRegex(ValueError, 'Invalid or duplicate'):
            overlay(self.bundled, dict(self.remote, files=[row('lua/client.lua', b'no')]))
        with self.assertRaisesRegex(ValueError, 'newer Starter'):
            overlay(self.bundled, dict(self.remote, maps={'Stonehenge': '0' * 64}))

    def test_bundled_map_join_does_not_wait_for_background_update(self):
        fingerprint = map_catalog(self.bundled)['Stonehenge']
        self.sync.available = True
        with patch.object(self.sync, 'refresh') as refresh:
            self.assertIsNone(self.sync.revision_for('Stonehenge', fingerprint))
        refresh.assert_not_called()
