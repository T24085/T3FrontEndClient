import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from community_transport import CommunityError
from direct_client import DirectClient


class CommunityHostTargetTests(unittest.TestCase):
    def setUp(self):
        self.client = DirectClient(dict(format=1, hostname='clanwars.example.com', public_address='8.8.8.8',
                                        https_port=18443, first_udp_port=18443, last_udp_port=18447,
                                        access_token='a' * 43))
        self.addCleanup(self.client.close)
        self.target = dict(id='b' * 32, address='1.1.1.1', port=19043, map='HighOctane2026',
                           contentHash='c' * 64, communityHost=True,
                           udpGrant=dict(id='d' * 32, key='e' * 64, matchId='b' * 32,
                                         expires=int(time.time()) + 60, port=19043))

    def test_private_match_uses_assigned_worker_instead_of_coordinator(self):
        with patch('direct_client.UdpClient') as udp:
            udp.return_value.port = 59321
            result = self.client._validated_target(self.target, 'HighOctane2026')
        self.assertEqual(result['endpoint'], '127.0.0.1:59321')
        udp.assert_called_once_with('1.1.1.1', self.target['udpGrant'])
        self.assertEqual(self.client.request_headers()['X-Community-Host'], '1')

    def test_worker_routes_are_rejected_for_lan_public_ctf_and_spectators(self):
        for target, flags in ((dict(self.target, address='192.168.1.10'), {}),
                              (self.target, {'public': True}), (self.target, {'spectator': True}),
                              (dict(self.target, communityHost=False), {})):
            with self.subTest(target=target, flags=flags), self.assertRaises(CommunityError):
                self.client._validated_target(target, 'HighOctane2026', **flags)
