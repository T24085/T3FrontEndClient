import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from community_transport import CommunityError
from direct_client import DirectClient, ENROLL_ROUTE, RegionalServerPicker, connect_regional, main, regional_server_rows


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

    def test_regional_directory_filters_expired_unsupported_and_nonpublic_endpoints(self):
        now = 100
        base = dict(server_id='a'*64, name='Atlanta', region='US East', hostname='atl.example.com',
                    address='1.1.1.1', port=18443, protocol=1, mode='regional', expires_at=150,
                    private_enrollment={'first_udp_port':18000,'last_udp_port':18004})
        rows = [base, dict(base, server_id='b'*64, expires_at=99),
                dict(base, server_id='c'*64, protocol=2), dict(base, server_id='d'*64, address='127.0.0.1')]
        result = regional_server_rows({'format':1,'listings':[{'payload':row} for row in rows]}, now)
        self.assertEqual(list(result),['a'*64])
        self.assertEqual(result['a'*64][2]['first_udp_port'],18000)

    def test_regional_enrollment_sends_only_the_host_bound_ticket(self):
        endpoint = dict(hostname='atl.example.com',https_port=18443,public_address='1.1.1.1',
                        first_udp_port=18000,last_udp_port=18004)
        broker = Mock(context=self.client.context)
        broker._request.return_value = {'ticket':'t'*43}
        with patch('direct_client.DirectClient') as enroll:
            enroll.return_value._request.return_value = {'registered':True,'device_id':3,'access_token':'r'*43}
            connection = connect_regional(broker,'a'*64,endpoint)
        broker._request.assert_called_once_with('regional-ticket',{'server_id':'a'*64},use_lobby_token=False)
        enroll.return_value._request.assert_called_once_with(ENROLL_ROUTE.removeprefix('/api/'),
                                                              {'regional_ticket':'t'*43},use_lobby_token=False)
        enroll.return_value.close.assert_called_once()
        self.assertEqual(connection,dict(endpoint,format=1,access_token='r'*43))

    def test_picker_keeps_connection_on_error_or_when_a_lobby_is_open(self):
        picker = RegionalServerPicker.__new__(RegionalServerPicker)
        picker.desktop = SimpleNamespace(closing=False,room=None,watch_id=None,game_status='idle',busy=False)
        picker.desktop.run_async = lambda work, done: (done(work()),True)[1]
        picker.coordinator = self.client
        picker.selected = None
        picker.choices = [(None,'Primary',None),('a'*64,'Atlanta',{'hostname':'atl.example.com'})]
        picker.menu = Mock(); picker.menu.current.return_value = 1
        picker.status = Mock(); picker.on_switch = Mock()
        with patch('direct_client.connect_regional',side_effect=CommunityError('Connection refused')) as open_host:
            picker.connect()
            picker.on_switch.assert_not_called()
            picker.status.configure.assert_called_with(text='Connection refused')
            picker.desktop.room = {'phase':'setup'}
            picker.connect()
            open_host.assert_called_once()
        picker.desktop.room = None
        selected = dict(self.client.connection,hostname='atl.example.com')
        with patch('direct_client.connect_regional',return_value=selected), patch('direct_client.DirectClient') as target:
            picker.connect()
            target.assert_called_once_with(selected,ssl_context=self.client.context)
            target.return_value.capabilities.assert_called_once()
        picker.on_switch.assert_called_once_with(selected,('a'*64,'Atlanta'))

    def test_windows_reopens_the_browser_with_the_selected_connection(self):
        primary = self.client.connection
        selection = (dict(primary,hostname='atl.example.com'),('a'*64,'Atlanta'))
        ready = Mock()
        with patch('direct_client.show_direct_starter',side_effect=[(primary,selection),None]) as show:
            main(Path('package'),on_ready=ready)
        self.assertEqual(show.call_count,2)
        show.assert_called_with(Path('package'),primary=primary,selected=selection,on_ready=None)

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
