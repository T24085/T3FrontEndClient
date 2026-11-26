"""Local Play checks for endpoint pinning and staged map reuse."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'src'), str(HERE.parents[1])]

from direct_client import DirectClient, LocalDirectClient, LocalHostSession, OfflineLobby
from community_transport import CommunityError


class LocalPlayClientTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def test_local_endpoint_requires_private_pinned_identity(self):
        address = {'format': 1, 'hostname': 'localhost', 'public_address': '127.0.0.1',
                   'https_port': 49200, 'first_udp_port': 49201, 'last_udp_port': 49201,
                   'access_token': 'a' * 43}
        (self.base/'local-host.pem').touch()
        connection = self.base/'connection.json'
        connection.write_text(json.dumps(address), encoding='utf-8')
        with self.assertRaises(ValueError):
            DirectClient(address)
        with patch('direct_client.ssl.SSLContext') as context:
            context.return_value.verify_mode = 2
            context.return_value.check_hostname = True
            local = LocalDirectClient(self.base)
            context.return_value.load_verify_locations.assert_called_once_with(cafile=str(self.base/'local-host.pem'))
            with self.assertRaisesRegex(CommunityError, 'cannot hand off'):
                local._validated_target({'communityHost': True}, 'Player')
            local.close()
        for changed in ({'hostname':'example.com'}, {'public_address':'127.0.0.2'},
                        {'first_udp_port':49200}):
            connection.write_text(json.dumps(dict(address, **changed)), encoding='utf-8')
            with self.assertRaises(ValueError):
                LocalDirectClient(self.base)

    def test_runtime_stages_shared_map_from_verified_player_inventory(self):
        bundle = self.base/'player'
        shared = 'content/Community/Stonehenge/Fixture.uasset'
        paths = ('local-host/operator/direct_service.py', 'local-host/host/package-manifest.json',
                 'local-host/shared-content.json', 'python/python.exe', shared)
        rows = []
        for index, name in enumerate(paths):
            path = bundle/name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps({'format':1,'paths':[shared]}).encode() if index == 2 else b'fixture'
            path.write_bytes(content)
            rows.append(dict(path=name,bytes=len(content),sha256=sha256(content).hexdigest()))
        (bundle/'package-manifest.json').write_text(json.dumps({'files':rows}), encoding='utf-8')
        session = LocalHostSession(bundle, self.base, self.base/'workspace')
        staging = self.base/'staged'
        files, shared_paths = session.verify_runtime()
        session.stage_runtime(staging, files, shared_paths)
        self.assertEqual((staging/'host'/shared).read_bytes(), (bundle/shared).read_bytes())
        (bundle/'local-host/operator/unlisted.py').touch()
        with self.assertRaisesRegex(CommunityError, 'differ'):
            session.verify_runtime()

    def test_offline_launcher_does_not_use_network(self):
        with patch('community_transport.PinnedHTTPSConnection') as network:
            with self.assertRaisesRegex(CommunityError, 'remote host is unavailable'):
                OfflineLobby().capabilities()
            network.assert_not_called()
