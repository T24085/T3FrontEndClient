
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from server_browser import ServerBrowserWindow, ServerDirectory, filter_rows
from server_directory import CACHE_SECONDS, DirectoryError, canonical, encode_blob, key_id, signed_bytes


def modulus(key):
    return key.public_key().public_numbers().n.to_bytes(key.key_size // 8, 'big')


def signed(key, kind, fields):
    signature = key.sign(signed_bytes(kind, fields), padding.PKCS1v15(), hashes.SHA256())
    return {'payload': fields, 'signature': encode_blob(signature)}


class BrowserTest(unittest.TestCase):
    def test_expired_seed_recovers_through_pinned_masters_without_replay(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = encode_blob(modulus(key))
        now = 1780000000
        old_origin = 'https://directory-old.example.com'
        new_origin = 'https://directory-new.example.com'

        def trust(revision, origin, *, issued=now, lifetime=3600, signer=key):
            return signed(signer, 'trust', {'format': 1, 'revision': revision, 'masters': [origin],
                                          'groups': [], 'issued_at': issued, 'expires_at': issued + lifetime})

        expired = trust(2, old_origin, issued=now - CACHE_SECONDS - 172800)
        feed = {'format': 1, 'trust': trust(1, old_origin), 'revocations': [], 'listings': []}
        origins = []

        def fetch(origin, _):
            origins.append(origin)
            return feed

        with TemporaryDirectory() as folder:
            root = Path(folder)
            seed = root / 'seed.json'
            seed.write_bytes(canonical({'root': public, 'trust': expired}))
            directory = ServerDirectory(seed, root / 'local', clock=lambda: now, fetch=fetch)
            directory.refresh()
            self.assertFalse(directory.online)
            self.assertEqual(directory.index.trust_payload['revision'], 2)
            self.assertEqual(origins, [old_origin])

            feed['trust'] = trust(3, new_origin, signer=other_key)
            directory.refresh()
            self.assertFalse(directory.online)
            self.assertEqual(directory.rows(), [])
            self.assertEqual(origins, [old_origin, old_origin])

            feed['trust'] = trust(3, new_origin, lifetime=20)
            feed['listings'] = [signed(key, 'heartbeat', {
                'format': 1, 'server_id': key_id(public), 'key': public, 'name': 'New Host',
                'region': 'US West', 'hostname': 'west.example.com', 'address': '93.184.216.34',
                'port': 18443, 'protocol': 1, 'version': 'r76', 'mode': 'regional', 'map': 'Drydock',
                'game_type': 'CTF', 'players': 1, 'max_players': 24, 'spectators': 0, 'locked': False,
                'memberships': [], 'issued_at': now, 'expires_at': now + 60,
            })]
            directory.refresh()
            self.assertTrue(directory.online)
            self.assertEqual(directory.index.trust_payload['masters'], [new_origin])
            self.assertEqual(origins[-2:], [old_origin, new_origin])
            self.assertTrue(directory.rows()[0]['live'])
            now += 21
            [cached] = directory.rows()
            self.assertFalse(cached['live'])
            self.assertGreater(cached['expires_at'], now)
            self.assertLess(cached['live_until'], now)
            now += CACHE_SECONDS + 60
            restored = ServerDirectory(seed, root / 'local', clock=lambda: now)
            self.assertEqual(restored.index.trust_payload['masters'], [new_origin])
            self.assertEqual(restored.rows(), [])

    def test_signed_list_falls_back_to_saved_rows_with_favourites_and_history(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = encode_blob(modulus(key))
        ident = key_id(public)
        self.now = 1780000000
        origins = ('https://directory-a.example.com', 'https://directory-b.example.com')
        trust = signed(key, 'trust', {'format':1, 'revision':1, 'issued_at':self.now, 'expires_at':self.now+600,
                                      'masters':list(origins), 'groups':[]})
        listing = signed(key, 'heartbeat', {
            'format':1, 'server_id':ident, 'key':public, 'name':'West CTF', 'region':'US West',
            'hostname':'west.example.com', 'address':'93.184.216.34', 'port':18443,
            'protocol':1, 'version':'r76', 'mode':'regional', 'map':'Drydock', 'game_type':'CTF',
            'players':24, 'max_players':24, 'spectators':1, 'locked':True, 'memberships':[],
            'issued_at':self.now, 'expires_at':self.now+60,
        })
        feed = {'format':1, 'trust':trust, 'revocations':[], 'listings':[listing]}

        def other_master(origin, _):
            if origin == origins[0]:
                raise OSError('First master unavailable.')
            return feed

        def offline(*_):
            raise OSError('All masters unavailable.')

        with TemporaryDirectory() as folder:
            root = Path(folder)
            seed = root/'seed.json'
            seed.write_bytes(canonical({'root':public, 'trust':trust}))
            directory = ServerDirectory(seed, root/'local', clock=lambda:self.now, fetch=other_master)
            directory.refresh()
            self.assertTrue(directory.online)
            [row] = directory.rows()
            self.assertTrue(row['live'])
            self.assertFalse(filter_rows([row], full=True))
            self.assertFalse(filter_rows([row], locked=True))
            self.assertFalse(filter_rows([row], region='Europe'))
            directory.toggle_favourite(ident)
            directory.connected(ident)
            online_rows = directory.rows()
            self.assertEqual(filter_rows(online_rows, favourites=True, recent=True), online_rows)
            self.now += 61
            self.assertFalse(directory.rows())
            directory.fetch = offline
            directory.refresh()
            self.assertFalse(directory.rows()[0]['live'])
            restored = ServerDirectory(seed, root/'local', clock=lambda:self.now, fetch=offline)
            restored.refresh()
            self.assertFalse(restored.online)
            [row] = restored.rows()
            self.assertFalse(row['live'])
            self.assertFalse(row['badges'])
            self.assertTrue(row['favourite'])
            self.assertTrue(row['recent'])

    @unittest.skipUnless(os.name == 'nt' or shutil.which('openssl'), 'Requires the packaged verifier')
    def test_packaged_verifier_accepts_only_the_listed_server_key(self):
        from server_directory import verify
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        document = signed(key, 'heartbeat', {'test': 1})
        with patch.dict(sys.modules, {'cryptography.exceptions': None}):
            self.assertEqual(verify(document, 'heartbeat', encode_blob(modulus(key))), {'test': 1})
            with self.assertRaises(DirectoryError):
                verify(document, 'heartbeat', encode_blob(modulus(other)))
            with self.assertRaises(DirectoryError):
                verify(dict(document, payload={'test': 2}), 'heartbeat', encode_blob(modulus(key)))

    def test_invitations_must_match_selected_server_endpoint(self):
        here = Path(__file__).parent/'experimental/direct-hosting/src'
        with patch.object(sys, 'path', [str(here), *sys.path]):
            from direct_client import invitation_for_server
        row = {'hostname':'west.example.com', 'address':'93.184.216.34', 'port':18443, 'protocol':1}
        invite = {'format':1, 'hostname':'west.example.com', 'public_address':'93.184.216.34', 'https_port':18443,
                  'first_udp_port':18443, 'last_udp_port':18447, 'access_token':'t'*43}
        self.assertEqual(invitation_for_server(row, invite), invite)
        group = dict(invite, host_id='a'*32, enrollment_token='g'*43)
        del group['access_token']
        self.assertEqual(invitation_for_server(row, group), group)
        with self.assertRaisesRegex(ValueError, 'selected server'):
            invitation_for_server(dict(row, address='93.184.216.35'), invite)
        with self.assertRaisesRegex(ValueError, 'protocol'):
            invitation_for_server(dict(row, protocol=2), invite)

    def test_changing_hosts_checks_for_a_game_started_during_connection(self):
        here = Path(__file__).parent/'experimental/direct-hosting/src'
        with patch.object(sys, 'path', [str(here), *sys.path]):
            import direct_client
        browser = Mock()
        gui = SimpleNamespace(root=Mock(), sidebar=Mock(), button=Mock(), close=Mock(), closing=False,
                              room=None, watch_id=None, controls_busy=False, game=None, game_status='idle',
                              public_panel=SimpleNamespace(pending=set()))
        selected = Mock()
        with patch('server_browser.ServerBrowserWindow', return_value=browser) as show, \
                patch.object(direct_client, 'choose_directory_connection') as connect:
            direct_client.add_server_directory(gui, Mock(), Path('.'), selected)
            gui.button.call_args.args[2]()
            handlers = show.call_args.kwargs
            handlers['connect']({'name': 'New server'}, browser)
            connect.assert_called_once()
            gui.public_panel.pending.add('start')
            handlers['connect'](None, browser)
            connect.assert_called_once()
            handlers['on_connected']({'host': 'new'})
            selected.assert_not_called()
            gui.close.assert_not_called()
            browser.status.set.assert_called_with('Leave the current lobby or game before changing servers.')
            browser.window.after.assert_called_once()
            gui.public_panel.pending.clear()
            handlers['on_connected']({'host': 'new'})
            selected.assert_called_once_with({'host': 'new'})
            gui.close.assert_called_once()

    def test_open_invitation_does_not_require_a_selected_listing(self):
        browser = SimpleNamespace(connect=Mock(), pending={'refresh'})
        ServerBrowserWindow.open_invitation(browser)
        browser.connect.assert_called_once_with(None, browser)
        browser.pending.add('connect')
        ServerBrowserWindow.open_invitation(browser)
        browser.connect.assert_called_once()

    def test_unlisted_host_accepts_both_invitation_types_after_the_capability_check(self):
        here = Path(__file__).parent/'experimental/direct-hosting/src'
        with patch.object(sys, 'path', [str(here), *sys.path]):
            import direct_client
        invitation = {
            'format': 1, 'hostname': 'unlisted.example.com', 'public_address': '93.184.216.34',
            'https_port': 18443, 'first_udp_port': 18443, 'last_udp_port': 18447, 'access_token': 't'*43,
        }
        group = dict(invitation, host_id='a'*32, enrollment_token='g'*43)
        del group['access_token']
        directory = Mock()
        with TemporaryDirectory() as folder:
            local = Path(folder)
            invite_file = local/'unlisted.json'
            browser = Mock()
            client = Mock()
            picker = SimpleNamespace(filedialog=SimpleNamespace(askopenfilename=Mock(return_value=str(invite_file))))
            for data in (invitation, group):
                invite_file.write_bytes(canonical(data))
                with self.subTest(group=data is group), \
                        patch.dict(sys.modules, {'tkinter': picker}), \
                        patch.object(direct_client, 'DirectClient', return_value=client) as connect, \
                        patch.object(direct_client, 'enroll_group_connection', return_value=invitation) as enroll:
                    direct_client.choose_directory_connection(directory, local, None, browser)
                    task, verify = browser.submit.call_args.args
                    self.assertEqual(task, 'connect')
                    client.capabilities.return_value = {'gameClientReady': False}
                    with self.assertRaisesRegex(DirectoryError, 'current game client'):
                        verify()
                    client.capabilities.return_value = {'gameClientReady': True}
                    self.assertEqual(verify(), invitation)
                    self.assertEqual(connect.call_count, 2)
                    self.assertEqual(enroll.call_count, 2 if data is group else 0)
            self.assertEqual(client.close.call_count, 4)
            self.assertFalse((local/'directory-invitations').exists())
            directory.connected.assert_not_called()


if __name__ == '__main__':
    unittest.main()
