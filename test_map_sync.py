import gzip
import hashlib
from http.client import HTTPResponse
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from map_sync import MapSync, load_overlay, overlay
from map_sync_contract import (MAP_ARCHIVE_ASSETS, MAP_ARCHIVE_NAME,
                               SESSION_CORE, SESSION_INDEX, SESSION_MAP, SESSION_SHARED,
                               encode, map_catalog, sha256_bytes)
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

    def test_per_map_sync_has_no_startup_request_and_reuses_only_shared_files(self):
        names = ('Stonehenge', 'Rollercoaster')
        prefix = 'content/Community/SharedFixture/'
        data = {prefix + 'Shared.uasset': b'shared'}
        files = {}
        for name in names:
            level = f'content/Maps/Community/{name}/Arena_{name}_P'
            files[name] = [row(path, path.encode()) for path in
                           (level + '.umap', level + '.uexp', f'content/Community/{name}/Prop.uasset')]
            data.update({item['path']:item['path'].encode() for item in files[name]})
        shared = [row(path, raw) for path, raw in data.items() if path.startswith(prefix)]
        catalog = map_catalog(dict(self.bundled, community_maps=list(names),
                                   map_runtime=dict.fromkeys(names, []), shared_content={prefix: list(names)},
                                   files=[self.bundled['files'][0], *shared, *files[names[0]], *files[names[1]]]))
        core = {'format':3, 'baseGameHash':self.bundled['files'][0]['sha256']}
        shared_doc = {'format':3, 'files':shared, 'prefixes':[prefix]}
        core_hash, shared_hash = sha256_bytes(encode(core)), sha256_bytes(encode(shared_doc))
        docs = {SESSION_CORE:core, SESSION_SHARED+shared_hash:shared_doc}
        meta = []
        for name in names:
            document = {'format':3, 'id':name, 'contentHash':catalog[name], 'coreHash':core_hash,
                        'sharedHash':shared_hash, 'definition':None, 'files':files[name], 'objectives':[], 'runtime':[]}
            docs[SESSION_MAP + name] = document
            meta.append({'id':name, 'label':name, 'gameTag':'Community', 'hasObjectives':False,
                         'bytes':sum(item['bytes'] for item in files[name]+shared), 'fileCount':4,
                         'contentHash':catalog[name], 'manifestHash':sha256_bytes(encode(document))})
        docs[SESSION_INDEX] = {'format':3, 'maps':meta, 'coreHash':core_hash}
        requests, transfers = [], []

        def document(path, fingerprint=None):
            requests.append(path)
            response = docs[path]
            if fingerprint is not None:
                self.assertEqual(sha256_bytes(encode(response)), fingerprint)
            return response

        def download(item, destination):
            transfers.append(item['path'])
            self.sync._write_asset(BytesIO(data[item['path']]), destination, item['sha256'], item['bytes'])

        with (patch.object(self.sync, '_document', side_effect=document),
              patch.object(self.sync, '_download', side_effect=download)):
            self.sync.start(2, session_version=3)
            self.assertEqual(requests, [])
            index = self.sync.map_index()
            self.assertTrue(all(item['state'] == 'Not downloaded' for item in self.sync.local_maps(index)))
            first = meta[0]
            version = self.sync.revision_for(first['id'], first['contentHash'], first['manifestHash'])
            self.assertEqual(requests, [SESSION_INDEX, SESSION_MAP+first['id'], SESSION_CORE, SESSION_SHARED+shared_hash])
            self.assertEqual(set(transfers), {item['path'] for item in files[first['id']]+shared})
            entries, current, _, _ = load_overlay(self.root, version, self.bundled)
            self.assertEqual(current, {first['id']: first['contentHash']})
            self.assertEqual(len(entries), 4)
            requests.clear()
            transfers.clear()
            self.assertEqual(self.sync.revision_for(first['id'], first['contentHash'], first['manifestHash']), version)
            self.assertEqual((requests, transfers), ([], []))
            second = meta[1]
            self.sync.revision_for(second['id'], second['contentHash'], second['manifestHash'])
            self.assertEqual(set(transfers), {item['path'] for item in files[second['id']]})
            self.assertTrue(all(item['state'] == 'Downloaded' for item in self.sync.local_maps(index)))
            changed = dict(first, manifestHash='b'*64)
            self.assertEqual(self.sync.local_maps([changed])[0]['state'], 'Update available')
            self.sync.remove_map(first['id'])
            state = {item['id']:item['state'] for item in self.sync.local_maps(index)}
            self.assertEqual(state, {first['id']:'Not downloaded', second['id']:'Downloaded'})
            for item in files[first['id']]:
                self.assertFalse(self.sync.session_path(item['sha256'] + '.asset').exists())
            self.assertTrue(self.sync.session_path(shared[0]['sha256'] + '.asset').is_file())

    def test_map_manifest_with_the_wrong_hash_is_rejected(self):
        response = self.inventory_connection(b'{}', 2)
        with (patch.object(self.sync, 'lobby', Mock()), patch.object(self.sync, '_connection', return_value=response)):
            with self.assertRaisesRegex(ValueError, 'manifest changed'):
                self.sync._document(SESSION_MAP + 'Stonehenge', 'a'*64)

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
