
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from server_browser import ServerDirectory, filter_rows
from server_directory import DirectoryError, canonical, encode_blob, key_id, signed_bytes


def modulus(key):
    return key.public_key().public_numbers().n.to_bytes(key.key_size // 8, 'big')


def signed(key, kind, fields):
    signature = key.sign(signed_bytes(kind, fields), padding.PKCS1v15(), hashes.SHA256())
    return {'payload': fields, 'signature': encode_blob(signature)}


class BrowserTest(unittest.TestCase):
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

    @unittest.skipUnless(os.name == 'nt', 'Windows and Proton package use the CNG verifier')
    def test_packaged_verifier_accepts_only_the_listed_server_key(self):
        from starter_update_signing import verify
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        payload = signed_bytes('heartbeat', {'test': 1})
        signature = key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        self.assertTrue(verify(payload, signature, modulus=modulus(key)))
        self.assertFalse(verify(payload + b'altered', signature, modulus=modulus(key)))

    def test_invitations_must_match_selected_server_endpoint(self):
        import sys
        from unittest.mock import patch
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


if __name__ == '__main__':
    unittest.main()
