import gzip
import hashlib
from http.client import HTTPResponse
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from map_sync import MapSync, load_overlay, overlay
from map_sync_contract import MAP_ARCHIVE_ASSETS, MAP_ARCHIVE_NAME, map_catalog
from community_maps import custom_definitions, lua_map_definitions
from client_bootstrap import CONTRACT, map_name

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

    def inventory_connection(self, body, length):
        wire = (f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                f'Content-Length: {length}\r\n\r\n').encode('ascii') + body
        response = HTTPResponse(Mock(makefile=Mock(return_value=BytesIO(wire))))
        response.begin()
        return Mock(getresponse=Mock(return_value=response))

    def test_inventory_retries_truncated_http_body(self):
        body = json.dumps(self.remote).encode()
        truncated = self.inventory_connection(body[:-12], len(body))
        complete = self.inventory_connection(body, len(body))
        with (
            patch.object(self.sync, 'lobby', Mock()),
            patch.object(self.sync, '_connection', side_effect=[truncated, complete]) as connect,
            patch.object(self.sync.cancelled, 'wait') as wait,
        ):
            self.assertEqual(MapSync._inventory(self.sync), self.remote)
        self.assertEqual(connect.call_count, 2)
        wait.assert_called_once_with(1)
        truncated.close.assert_called_once()
        complete.close.assert_called_once()

    def test_inventory_reports_interruption_after_repeated_truncation(self):
        with (
            patch.object(self.sync, 'lobby', Mock()),
            patch.object(self.sync, '_connection', side_effect=lambda: self.inventory_connection(b'{}', 12)) as connect,
            patch.object(self.sync.cancelled, 'wait'),
        ):
            with self.assertRaisesRegex(RuntimeError, 'map catalog download was interrupted'):
                MapSync._inventory(self.sync)
        self.assertEqual(connect.call_count, 3)

    def test_matching_package_checks_metadata_without_downloading(self):
        self.remote = self.remote_for(self.bundled['files'][1:])
        with patch.object(self.sync, '_download') as download:
            self.assertEqual(self.sync.refresh(), (None, self.remote['maps']))
        download.assert_not_called()
        self.assertFalse((self.root / 'map-downloads').exists())

    def test_join_fetches_changed_revision_and_next_start_reuses_it(self):
        fingerprint = self.remote['maps']['Stonehenge']
        self.sync.available = True

        def inventory():
            self.assertEqual(self.sync.status, 'Checking for map updates...')
            return self.remote

        def fetch(entry, target):
            self.assertEqual(self.sync.status, 'Downloading map updates (1/1 files)...')
            self.assertEqual(entry['path'], ASSET)
            self.sync._write_verified(BytesIO(gzip.compress(b'new')), target, entry['sha256'], entry['bytes'])

        with (
            patch.object(self.sync, '_inventory', side_effect=inventory),
            patch.object(self.sync, '_download', side_effect=fetch) as download,
        ):
            revision = self.sync.revision_for('Stonehenge', fingerprint)
            download.assert_called_once()
        self.assertEqual(self.sync.status, 'Maps up to date.')
        entries, catalog, custom, objectives = load_overlay(self.root, revision, self.bundled)
        self.assertFalse(objectives)
        self.assertEqual(custom, {})
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

    def test_shared_zip_beside_launcher_supplies_only_authenticated_map_files(self):
        package = self.root / 'Client Files'
        package.mkdir()
        self.manifest.replace(package / 'package-manifest.json')
        self.sync.package = package
        sha = row(ASSET, b'new')['sha256']
        with ZipFile(self.root / MAP_ARCHIVE_NAME, 'w') as archive:
            archive.writestr(MAP_ARCHIVE_ASSETS + sha + '.asset', b'new')
            archive.writestr('../outside.dat', b'not an install member')
        with patch.object(self.sync, '_download') as download:
            revision, catalog = self.sync.refresh()
        download.assert_not_called()
        self.assertEqual(catalog, self.remote['maps'])
        entries, _, _, _ = load_overlay(self.root, revision, self.bundled)
        imported = {entry['path']: target for entry, _, target in entries}
        self.assertEqual(imported[ASSET].read_bytes(), b'new')
        self.assertFalse((self.root.parent / 'outside.dat').exists())

    def test_bad_zip_asset_falls_back_to_host_download(self):
        sha = row(ASSET, b'new')['sha256']
        with ZipFile(self.root / MAP_ARCHIVE_NAME, 'w') as archive:
            archive.writestr(MAP_ARCHIVE_ASSETS + sha + '.asset', b'bad')

        def download(entry, target):
            self.assertFalse(target.exists())
            self.sync._write_verified(BytesIO(gzip.compress(b'new')), target, sha, entry['bytes'])

        with patch.object(self.sync, '_download', side_effect=download) as fetch:
            revision, _ = self.sync.refresh()
        fetch.assert_called_once()
        self.assertEqual((self.root / 'map-downloads' / (sha + '.asset')).read_bytes(), b'new')
        self.assertTrue((self.root / 'map-downloads' / (revision + '.json')).is_file())

    def test_bad_gzip_hash_or_size_cannot_publish_revision(self):
        bad_payloads = (gzip.compress(b'bad'), gzip.compress(b'new extra'), gzip.compress(b'new')[:-4])
        for raw in bad_payloads:
            with self.subTest(payload=raw), patch.object(self.sync, '_download', side_effect=lambda entry, target:
                    self.sync._write_verified(BytesIO(raw), target, entry['sha256'], entry['bytes'])):
                with self.assertRaisesRegex(RuntimeError, 'Map update failed'):
                    self.sync.refresh()
                self.assertEqual(list((self.root / 'map-downloads').iterdir()), [])

    def test_objectives_refresh_even_when_the_cooked_fingerprint_is_unchanged(self):
        self.remote = dict(self.remote_for(self.bundled['files'][1:]), format=2,
                           community_maps=['Stonehenge'], map_definitions={})
        map_id = 'Stonehenge'
        fingerprint = self.remote['maps'][map_id]
        path = 'lua/Stonehenge/objectives.lua'
        self.sync.available = True
        self.sync.version = 2
        revisions = []
        for raw in (b'return {weather=false}', b'return {weather={kind="rain"}}'):
            entry = row(path, raw)
            self.remote['objectives'] = [entry]
            with patch.object(self.sync, '_download', side_effect=lambda item, target:
                    self.sync._write_verified(BytesIO(gzip.compress(raw)), target, item['sha256'], item['bytes'])):
                revision = self.sync.revision_for(map_id, fingerprint)
            revisions.append(revision)
            entries, catalog, _, objectives = load_overlay(self.root, revision, self.bundled)
            self.assertTrue(objectives)
            self.assertEqual(catalog[map_id], fingerprint)
            self.assertEqual(entries[-1][2].read_bytes(), raw)
        self.assertNotEqual(*revisions)
        with self.assertRaisesRegex(ValueError, 'Invalid map objectives'):
            overlay(self.bundled, dict(self.remote, objectives=[row('lua/client.lua', b'return {}')]))

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

    def test_new_host_map_downloads_and_supplies_the_verified_bootstrap(self):
        custom = {'NewMap': {'label': 'New Map', 'asset_group': 'NewMap', 'level': 'Arena_NewMap_P'}}
        extra = {'content/Maps/Community/NewMap/Arena_NewMap_P.umap': b'level',
                 'content/Maps/Community/NewMap/Arena_NewMap_P.uexp': b'export',
                 'content/Community/NewMap/Decor.uasset': b'decor'}
        host = dict(self.bundled, community_maps=['Stonehenge', 'NewMap'], map_definitions=custom,
                    map_runtime={'Stonehenge': [], 'NewMap': []},
                    files=self.bundled['files'] + [row(name, data) for name, data in extra.items()])
        self.remote = {'format': 2, 'maps': map_catalog(host), 'community_maps': host['community_maps'],
                       'map_definitions': custom, 'shared_content': {}, 'files': host['files'][1:]}
        self.sync.available = True
        requested = []

        def fetch(entry, target):
            requested.append(entry['path'])
            data = extra[entry['path']]
            self.sync._write_verified(BytesIO(gzip.compress(data)), target, entry['sha256'], len(data))

        with patch.object(self.sync, '_download', side_effect=fetch):
            revision = self.sync.revision_for('NewMap', self.remote['maps']['NewMap'])
        self.assertCountEqual(requested, [name for name in extra if not name.endswith('.uexp')])
        entries, catalog, definitions, objectives = load_overlay(self.root, revision, self.bundled)
        self.assertFalse(objectives)
        self.assertEqual(catalog, self.remote['maps'])
        selected = custom_definitions(definitions)['NewMap']
        self.assertEqual(map_name(CONTRACT, 'NewMap', definitions={selected.id: selected}), selected.package)
        runtime = lua_map_definitions(self.root, self.root, selected)
        self.assertIn('/Game/Maps/Community/NewMap/Arena_NewMap_P.Arena_NewMap_P:', runtime.read_text())
        self.assertEqual(len(entries), len(host['files']) - 1)

    def test_dynamic_definition_rejects_injection_and_builtin_aliases(self):
        for name, level in (('stonehenge', 'Arena_New_P'), ('NewMap', '../Unsafe'), ('NewMap', 'foo?listen')):
            with self.subTest(name=name, level=level), self.assertRaises(ValueError):
                custom_definitions({name: {'label': 'New Map', 'asset_group': 'NewMap', 'level': level}})
