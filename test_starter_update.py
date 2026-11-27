import ast
from base64 import b64decode, b64encode
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from direct_update_contract import LINUX_INDEX
from starter_update import (CHANNEL, DIRECT_CHANNEL, LINUX_CHANNEL, LINUX_CHUNK_BYTES,
                            INDEX, INVENTORY, accept, decode_index,
                            encoded, prepare, recover, run_startup, sha)


from tools.build_starter_update import bundled_boundary_launcher, bundled_client_entry


def envelope(files, revision=1, issued=None, channel=CHANNEL):
    issued = int(time.time()) if issued is None else issued
    payload = encoded({'channel': channel, 'revision': revision, 'issued': issued, 'expires': issued + 86400,
                       'files': {name: {'bytes': len(raw), 'sha256': sha(raw)} for name, raw in files.items()}})
    return encoded({'payload': b64encode(payload).decode(), 'signature': b64encode(payload).decode()})


def verify_fixture(payload, signature):
    return payload == signature


class StarterUpdateTest(unittest.TestCase):
    def test_signed_launcher_includes_boundary_controls_without_a_new_update_path(self):
        root = Path(__file__).resolve().parent
        launcher = bundled_boundary_launcher((root / 'desktop_launcher.py').read_bytes(), root)
        self.assertNotIn(b'from boundary_controls import', launcher)
        self.assertIn(b'class BoundaryDialog:', launcher)
        self.assertIn(b'boundary_summary = summary', launcher)
        compile(launcher, 'desktop_launcher.py', 'exec')


    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = self.root / '.starter-update'
        self.state.mkdir()
        self.files = {'lua/client.lua': b'-- old Lua\n', 'desktop_launcher.py': b'print("old")\n',
                      'lua/community_maps.lua': b'-- frozen\n', 'client-settings.json': b'{"private": true}'}
        for name, raw in self.files.items():
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)
        self.manifest = {'map_runtime': {'Katabatic': ['lua/community_maps.lua']},
                         'files': [{'path': n, 'bytes': len(raw), 'sha256': sha(raw)} for n, raw in self.files.items()]}
        self.inventory = self.root / INVENTORY
        self.inventory.write_bytes(encoded(self.manifest))
        self.requests = []

    def stage(self, files, *, revision=1, signed=None, replacement=None):
        blobs = {'starter-file-' + sha(raw) + '.bin': raw for raw in files.values()}

        def fetch(name, limit):
            self.requests.append(name)
            if name == INDEX:
                return signed if signed is not None else envelope(files, revision)
            return replacement if replacement is not None else blobs[name]

        return prepare(self.root, self.state, fetch=fetch, verifier=verify_fixture)

    def test_signed_client_payload_carries_weather_without_a_new_inventory_path(self):
        root = Path(__file__).resolve().parent
        weather = (root / 'lua/weather.lua').read_bytes()
        raw = bundled_client_entry((root / 'client_entry.py').read_bytes(), weather)
        assignment, = (node for node in ast.parse(raw).body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == '_SIGNED_WEATHER_MODULE'
                               for target in node.targets))
        self.assertEqual(ast.literal_eval(assignment.value), weather)

    def test_only_changed_files_download_and_inventory_remains_consistent(self):
        new = b'-- fixed Lua\n'
        self.assertTrue(self.stage({'lua/client.lua': new, 'desktop_launcher.py': self.files['desktop_launcher.py']}))
        self.assertEqual(self.requests, [INDEX, 'starter-file-' + sha(new) + '.bin'])
        accept(self.state)
        self.assertFalse(recover(self.root, self.state))
        self.assertEqual((self.root / 'lua/client.lua').read_bytes(), new)
        self.assertEqual((self.root / 'client-settings.json').read_bytes(), self.files['client-settings.json'])
        after = json.loads(self.inventory.read_bytes())
        self.assertEqual(after['map_runtime'], self.manifest['map_runtime'])
        self.assertEqual(after['starter_update_revision'], 1)
        self.assertEqual((self.state / 'previous/lua/client.lua').read_bytes(), self.files['lua/client.lua'])
        self.assertFalse(self.stage({'lua/client.lua': b'-- replay'}))

    def test_interrupted_start_restores_previous_files_and_skips_failed_revision(self):
        new = {'lua/client.lua': b'-- broken Lua\n', 'desktop_launcher.py': b'print("new")\n'}
        self.assertTrue(self.stage(new))
        self.assertTrue(recover(self.root, self.state))
        self.assertEqual(json.loads(self.inventory.read_bytes()), self.manifest)
        self.assertEqual((self.root / 'lua/client.lua').read_bytes(), self.files['lua/client.lua'])
        self.assertFalse(self.stage(new))
        self.assertTrue(self.stage({'lua/client.lua': b'-- fixed startup\n'}, revision=2))
        accept(self.state)

    def test_mid_install_failure_rolls_back_all_files(self):
        from starter_update import atomic_write

        def fail_once(path, raw):
            if path == self.inventory and raw != encoded(self.manifest):
                raise OSError('simulated failed manifest replacement')
            atomic_write(path, raw)

        with patch('starter_update.atomic_write', side_effect=fail_once), self.assertRaises(OSError):
            self.stage({'lua/client.lua': b'-- new\n'})
        self.assertEqual((self.root / 'lua/client.lua').read_bytes(), self.files['lua/client.lua'])
        self.assertEqual(json.loads(self.inventory.read_bytes()), self.manifest)
        self.assertFalse((self.state / 'pending').exists())

    def test_invalid_signature_path_expiry_and_payload_are_refused(self):
        new = {'lua/client.lua': b'-- new\n'}
        with self.assertRaisesRegex(ValueError, 'signature'):
            decode_index(envelope(new), verifier=lambda *_: False)
        for path in ('../desktop_launcher.py', 'client-settings.json', 'lua/community_maps.lua', 'starter_update.py'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'file path'):
                self.stage({path: b'-- unexpected\n'})
        with self.assertRaisesRegex(ValueError, 'validity period'):
            self.stage(new, signed=envelope(new, issued=1))
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            self.stage(new, replacement=b'-- modified\n')
        self.assertEqual(json.loads(self.inventory.read_bytes()), self.manifest)

    def test_cumulative_update_cannot_drop_a_previous_path(self):
        self.assertTrue(self.stage({'lua/client.lua': b'-- first\n'}))
        accept(self.state)
        with self.assertRaisesRegex(ValueError, 'previous revision'):
            self.stage({'desktop_launcher.py': b'print("second")\n'}, revision=2)

    def configure_direct(self):
        self.invitation = self.root / 'group-invitation.json'
        self.invitation.write_bytes(b'local invitation')
        self.direct = self.root / 'direct_client.py'
        self.original = b'print("original direct client")\n'
        self.direct.write_bytes(self.original)
        self.manifest['direct_host_contract'] = 'authenticated-udp-v1'
        self.manifest['files'].append({'path': self.direct.name, 'bytes': len(self.original),
                                       'sha256': sha(self.original)})
        self.inventory.write_bytes(encoded(self.manifest))

    def test_signed_indexes_are_bound_to_their_channel(self):
        raw = b'# update\n'
        regular = envelope({'lua/client.lua': raw})
        direct = envelope({'lua/client.lua': raw}, channel=DIRECT_CHANNEL)
        for index, channel in ((regular, DIRECT_CHANNEL), (direct, CHANNEL)):
            with self.assertRaisesRegex(ValueError, 'update channel'):
                decode_index(index, channel=channel, verifier=verify_fixture)
        for path in ('group-invitation.json', 'connection-policy.json', 'direct_starter.pyw'):
            with self.assertRaisesRegex(ValueError, 'unsupported file path'):
                decode_index(envelope({path: raw}, channel=DIRECT_CHANNEL),
                             channel=DIRECT_CHANNEL, verifier=verify_fixture)
        self.configure_direct()
        with self.assertRaisesRegex(ValueError, 'does not match this Starter package'):
            self.stage({'lua/client.lua': raw})

    def test_linux_update_uses_its_own_index_and_revision(self):
        self.configure_direct()
        files = {'desktop_launcher.py': b'print("Linux update")\n'}
        direct = envelope(files, channel=DIRECT_CHANNEL)
        with self.assertRaisesRegex(ValueError, 'update channel'):
            decode_index(direct, channel=LINUX_CHANNEL, verifier=verify_fixture)

        self.manifest.update(linux_starter_update_channel=LINUX_CHANNEL, starter_update_revision=74)
        self.inventory.write_bytes(encoded(self.manifest))
        linux = envelope(files, channel=LINUX_CHANNEL)

        def fetch(name, limit):
            self.requests.append(name)
            return linux if name == LINUX_INDEX else files['desktop_launcher.py']

        args = {'channel': LINUX_CHANNEL, 'fetch': fetch, 'verifier': verify_fixture}
        self.assertTrue(prepare(self.root, self.state, **args))
        after = json.loads(self.inventory.read_bytes())
        self.assertEqual(after['starter_update_revision'], 74)
        self.assertEqual(after['linux_starter_update_revision'], 1)
        self.assertEqual(self.requests, [LINUX_INDEX, 'starter-file-' + sha(files['desktop_launcher.py']) + '.bin'])
        self.assertTrue(recover(self.root, self.state, channel=LINUX_CHANNEL))
        self.assertEqual(json.loads(self.inventory.read_bytes()), self.manifest)
        self.assertFalse(prepare(self.root, self.state, **args))

    def test_linux_checks_individual_chunks_then_checks_the_reassembled_file(self):
        self.configure_direct()
        self.manifest['linux_starter_update_channel'] = LINUX_CHANNEL
        self.inventory.write_bytes(encoded(self.manifest))
        name = 'desktop_launcher.py'
        chunks = (b'#' * LINUX_CHUNK_BYTES, b'\nprint("new")\n')
        payload = json.loads(b64decode(json.loads(envelope({name: b''.join(chunks)}))['payload']))
        payload['channel'] = LINUX_CHANNEL
        row = payload['files'][name]
        row['chunks'] = [sha(part) for part in chunks]
        blobs = {f'starter-file-{sha(part)}.bin': part for part in chunks}

        def fetch(name, limit):
            if name != LINUX_INDEX:
                return blobs[name]
            raw = b64encode(encoded(payload)).decode()
            return encoded({'payload': raw, 'signature': raw})

        args = {'channel': LINUX_CHANNEL, 'fetch': fetch, 'verifier': verify_fixture}
        row['chunks'].reverse()
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            prepare(self.root, self.state, **args)
        self.assertEqual(json.loads(self.inventory.read_bytes()), self.manifest)
        row['chunks'].reverse()
        row['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            prepare(self.root, self.state, **args)
        row['sha256'] = sha(b''.join(chunks))
        self.assertTrue(prepare(self.root, self.state, **args))
        self.assertEqual((self.root/name).read_bytes(), b''.join(chunks))
        row = next(file for file in json.loads(self.inventory.read_bytes())['files'] if file['path'] == name)
        self.assertNotIn('chunks', row)

    @unittest.skipUnless(os.name == 'nt', 'Windows package lock required')
    def test_direct_launch_applies_before_import_and_recovers_a_failed_start(self):
        self.configure_direct()
        new = b'print("updated direct client")\n'
        signed = envelope({self.direct.name: new}, channel=DIRECT_CHANNEL)
        self.requested_revision = 1

        def fetch(name, _limit):
            self.requests.append(name)
            if name == INDEX:
                if self.requested_revision == 1:
                    return signed
                return envelope({self.direct.name: new}, revision=2, channel=DIRECT_CHANNEL)
            self.assertEqual(name, 'starter-file-' + sha(new) + '.bin')
            return new

        def decode(raw, *, channel, verifier):
            return decode_index(raw, channel=channel, verifier=verify_fixture)

        def fail_before_ready(on_ready):
            self.assertIsNotNone(on_ready)
            self.assertEqual(self.direct.read_bytes(), new)
            self.assertTrue((self.state / 'pending').is_dir())
            raise ImportError('simulated Direct startup failure')

        def accept_after_ready(on_ready):
            self.assertIsNotNone(on_ready)
            self.assertEqual(self.direct.read_bytes(), new)
            on_ready()

        with (patch('starter_update.fetcher', return_value=fetch) as downloader,
              patch('starter_update.decode_index', side_effect=decode)):
            with self.assertRaisesRegex(RuntimeError, 'previous Starter was restored'):
                run_startup(self.root, fail_before_ready, channel=DIRECT_CHANNEL)
            self.assertEqual(self.direct.read_bytes(), self.original)
            self.assertEqual(json.loads(self.inventory.read_bytes()), self.manifest)
            self.requested_revision = 2
            run_startup(self.root, accept_after_ready, channel=DIRECT_CHANNEL)
        downloader.assert_called_with(channel=DIRECT_CHANNEL, ssl_context=None, root=self.root)
        self.assertEqual(self.direct.read_bytes(), new)
        self.assertEqual(self.invitation.read_bytes(), b'local invitation')
        self.assertEqual((self.state / 'previous/direct_client.py').read_bytes(), self.original)
        self.assertFalse((self.state / 'pending').exists())


if __name__ == '__main__':
    unittest.main()
