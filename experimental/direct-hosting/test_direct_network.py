import hashlib,json,pathlib,secrets,socket,sys,tempfile,threading,time,unittest
from unittest.mock import Mock, patch
ROOT=pathlib.Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'src')]
from direct_network import InviteStore,ReplayWindow,UdpServer,UdpClient,frame,unframe,write_json,valid_public_address

class Echo:
    def __init__(self):
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.sock.bind(('127.0.0.1',0));self.sock.settimeout(.1);self.port=self.sock.getsockname()[1];self.peers=[];self.done=False
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while not self.done:
            try:
                data,peer=self.sock.recvfrom(65535);self.peers.append(peer);self.sock.sendto(data,peer)
            except socket.timeout:pass
            except OSError:break
    def close(self):self.done=True;self.thread.join(1);self.sock.close()

class DirectNetworkTests(unittest.TestCase):
    def test_existing_invitation_accepts_new_friend_host_slots_with_matching_admission(self):
        from community_transport import CommunityError
        from direct_client import DirectClient

        connection = {
            'format': 1, 'hostname': 'localhost', 'public_address': '127.0.0.1',
            'https_port': 18443, 'first_udp_port': 18000, 'last_udp_port': 18000,
            'access_token': 'x'*43,
        }
        client = DirectClient(connection, test_source='127.0.0.2')
        self.addCleanup(client.close)
        match = {'id':'match', 'map':'Stonehenge', 'contentHash':'a'*64,
                 'address':'127.0.0.1', 'port':18004}
        grant = {'matchId':'match', 'id':'grant', 'port':18004}
        with patch('direct_client.UdpClient') as proxy:
            proxy.return_value.port = 20500
            for bad in (dict(match, address='127.0.0.2', udpGrant=grant),
                        dict(match, port=18010, udpGrant=dict(grant, port=18010))):
                with self.assertRaisesRegex(CommunityError, 'differs from this invitation'):
                    client._validated_target(bad, 'Stonehenge')
            for missing in (match, dict(match, udpGrant=dict(grant, port=18000))):
                with self.assertRaisesRegex(CommunityError, 'admission is unavailable'):
                    client._validated_target(missing, 'Stonehenge')
            proxy.assert_not_called()
            target = client._validated_target(dict(match, udpGrant=grant), 'Stonehenge')
            self.assertEqual(target['endpoint'], '127.0.0.1:20500')
            proxy.assert_called_once_with('127.0.0.1', grant)

    def test_stock_invitation_accepts_migrated_ports_with_pinned_address_and_grant(self):
        from community_transport import CommunityError
        from direct_client import DirectClient

        connection = {'format': 1, 'hostname': 'localhost', 'public_address': '127.0.0.1',
                      'https_port': 443, 'first_udp_port': 18000, 'last_udp_port': 18004,
                      'access_token': 'x'*43}
        match = {'id': 'match', 'map': 'Stonehenge', 'contentHash': 'a'*64,
                 'address': '127.0.0.1', 'port': 18447}
        grant = {'matchId': 'match', 'id': 'grant', 'port': 18447}
        client = DirectClient(connection, test_source='127.0.0.2')
        self.addCleanup(client.close)
        custom = DirectClient(dict(connection, first_udp_port=17000, last_udp_port=17002),
                              test_source='127.0.0.2')
        self.addCleanup(custom.close)

        with patch('direct_client.UdpClient') as proxy:
            proxy.return_value.port = 20500
            for bad in (dict(match, address='127.0.0.2', udpGrant=grant),
                        dict(match, port=18453, udpGrant=dict(grant, port=18453)),
                        dict(match, port=18100, udpGrant=dict(grant, port=18100))):
                with self.assertRaisesRegex(CommunityError, 'differs from this invitation'):
                    client._validated_target(bad, 'Stonehenge')
            with self.assertRaisesRegex(CommunityError, 'differs from this invitation'):
                custom._validated_target(dict(match, udpGrant=grant), 'Stonehenge')
            with self.assertRaisesRegex(CommunityError, 'admission is unavailable'):
                client._validated_target(dict(match, udpGrant=dict(grant, port=18443)), 'Stonehenge')
            proxy.assert_not_called()

            target = client._validated_target(dict(match, udpGrant=grant), 'Stonehenge')
            self.assertEqual(target['endpoint'], '127.0.0.1:20500')
            proxy.assert_called_once_with('127.0.0.1', grant)

    def test_next_game_process_rotates_admission_without_changing_lobby_membership(self):
        from direct_client import DirectClient

        client = DirectClient({
            'format': 1, 'hostname': 'localhost', 'public_address': '127.0.0.1',
            'https_port': 18443, 'first_udp_port': 18000, 'last_udp_port': 18000,
            'access_token': 'x'*43,
        }, test_source='127.0.0.2')
        client.code, client.token, client.player_id = 'ABC234', 'lobby-token', 'player'
        first = client.direct_session
        old_proxy = Mock()
        client.proxies[('match', 'grant')] = old_proxy
        client.begin_game_attempt()
        old_proxy.close.assert_called_once()
        self.assertEqual(client.proxies, {})
        self.assertNotEqual(client.direct_session, first)
        self.assertEqual((client.code, client.token, client.player_id), ('ABC234', 'lobby-token', 'player'))

    def test_invites_store_hashes_and_revocation_fails_closed(self):
        with tempfile.TemporaryDirectory(dir=ROOT)as folder:
            store=InviteStore(pathlib.Path(folder)/'invites.json');a,token=store.issue('one');b,other=store.issue('two')
            self.assertNotEqual(store.peer(a).address,store.peer(b).address)
            self.assertEqual(store.authenticate(token),a)
            self.assertNotIn(token,store.path.read_text());self.assertNotIn(other,store.path.read_text())
            store.revoke(a)
            with self.assertRaises(ValueError):store.authenticate(token)
            self.assertEqual(store.authenticate(other),b)
            store.path.write_text('{broken');store.last_read=0
            self.assertFalse(store.active(b))

    def test_authenticated_out_of_order_and_replay(self):
        key=secrets.token_bytes(32);identity=secrets.token_hex(16);window=ReplayWindow()
        p=frame(key,identity,8,b'game',b'C')
        self.assertEqual(unframe(key,identity,p,b'C',window),b'game')
        self.assertIsNone(unframe(key,identity,p,b'C',window))
        self.assertEqual(unframe(key,identity,frame(key,identity,7,b'older',b'C'),b'C',window),b'older')
        self.assertIsNone(unframe(key,identity,frame(key,identity,99,b'forged',b'S'),b'C',window))
        self.assertEqual(window.high,8)
        self.assertIsNone(unframe(key,identity,p[:-1]+bytes([p[-1]^1]),b'C',window))

    def test_public_address_rejects_lan_loopback_and_overlay(self):
        for value in ('127.0.0.1','192.168.1.2','100.64.0.1','0.0.0.0'):
            with self.assertRaises(ValueError):valid_public_address(value)

    def test_two_same_ip_clients_round_trip_with_distinct_native_addresses(self):
        echo=Echo();allowed={('a'*32,1),('a'*32,2)};server=UdpServer('127.0.0.1',0,echo.port,lambda m,i:(m,i)in allowed)
        clients=[];games=[]
        try:
            for identity in (1,2):
                clients.append(UdpClient('127.0.0.1',server.grant('a'*32,identity)))
                game=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);game.bind(('127.0.0.1',0));game.settimeout(2);games.append(game)
            for index,(client,game)in enumerate(zip(clients,games)):
                data=('player-'+str(index)).encode();game.sendto(data,('127.0.0.1',client.port));self.assertEqual(game.recv(100),data)
            self.assertEqual({p[0]for p in echo.peers},{InviteStore.address(1),InviteStore.address(2)})
            allowed.remove(('a'*32,1));games[0].settimeout(.5);games[0].sendto(b'revoked',('127.0.0.1',clients[0].port))
            with self.assertRaises(socket.timeout):games[0].recv(100)
            games[1].sendto(b'still-live',('127.0.0.1',clients[1].port));self.assertEqual(games[1].recv(100),b'still-live')
        finally:
            for game in games:game.close()
            for client in clients:client.close()
            server.close();echo.close()

    def test_raw_udp_rejected_and_new_starter_session_rotates_key(self):
        echo=Echo();server=UdpServer('127.0.0.1',0,echo.port,lambda m,i:True);raw=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            raw.sendto(b'untrusted game packet',('127.0.0.1',server.public_port));time.sleep(.25);self.assertEqual(echo.peers,[])
            a=server.grant('b'*32,1,'session-one');self.assertEqual(a,server.grant('b'*32,1,'session-one'))
            b=server.grant('b'*32,1,'session-two');self.assertNotEqual(a['id'],b['id']);self.assertNotEqual(a['key'],b['key']);self.assertEqual(len(server.grants),1)
            raw.sendto(frame(bytes.fromhex(a['key']),a['id'],0,b'old grant',b'C'),('127.0.0.1',server.public_port));time.sleep(.25);self.assertEqual(echo.peers,[])
        finally:raw.close();server.close();echo.close()

    def test_stopped_match_invalidates_transport(self):
        echo=Echo();alive=[True];server=UdpServer('127.0.0.1',0,echo.port,lambda m,i:alive[0])
        try:
            server.grant('c'*32,1);alive[0]=False;server.prune();self.assertEqual(server.grants,{})
            with self.assertRaises(ValueError):server.grant('c'*32,1)
        finally:server.close();echo.close()

if __name__=='__main__':unittest.main(verbosity=2)
