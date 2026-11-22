
"""Signed public discovery data shared by Direct Host and Starter."""
import base64
import binascii
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit


VERSION = 1
PROTOCOL_VERSION = 1
DIRECTORY_PATH = '/v1/server-directory'
HEARTBEAT_PATH = DIRECTORY_PATH + '/heartbeat'
MAX_HEARTBEAT = 8192
MAX_RESPONSE = 3 * 1024 * 1024
MAX_SERVERS = 256
HEARTBEAT_SECONDS = 60
CLOCK_SKEW = 10
MAX_TRUST_AGE = 31 * 86400
CACHE_SECONDS = 7 * 86400
MAX_MASTERS = 8
MAX_GROUPS = 16
MAX_REVOKED = 512
MODULUS_BYTES = (256, 384, 512)
HEX_ID = re.compile(r'[a-f0-9]{64}')
DNS_LABEL = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
DNS_NAME = re.compile(rf'(?:{DNS_LABEL}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?')


class DirectoryError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), sort_keys=True, allow_nan=False).encode('ascii')


def read_json(raw, *, limit=MAX_RESPONSE):
    def unique(pairs):
        values = dict(pairs)
        if len(values) != len(pairs):
            raise DirectoryError('Repeated directory field.')
        return values

    def invalid_constant(_):
        raise DirectoryError('Invalid directory constant.')

    if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
        raise DirectoryError('Invalid directory document size.')
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise DirectoryError('Invalid directory document.') from exc


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names):
        raise DirectoryError('Invalid directory fields.')


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise DirectoryError('Invalid directory number.')
    return value


def _label(value, limit):
    if not isinstance(value, str) or not 0 < len(value) <= limit or not value.isprintable() or value != value.strip():
        raise DirectoryError('Invalid directory label.')
    return value


def _identity(value):
    if not isinstance(value, str) or HEX_ID.fullmatch(value) is None:
        raise DirectoryError('Invalid directory identity.')
    return value


def _blob(value):
    if not isinstance(value, str) or len(value) > 684:
        raise DirectoryError('Invalid directory credential.')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DirectoryError('Invalid directory credential.') from exc
    if encode_blob(raw) != value:
        raise DirectoryError('Invalid directory credential encoding.')
    return raw


def encode_blob(raw):
    return base64.b64encode(raw).decode('ascii')


def public_key(encoded):
    raw = _blob(encoded)
    if len(raw) not in MODULUS_BYTES or not raw[0] & 128 or not raw[-1] & 1:
        raise DirectoryError('Invalid directory RSA public key.')
    return raw


def key_id(encoded):
    return hashlib.sha256(public_key(encoded)).hexdigest()


def hostname(value):
    if (not isinstance(value, str) or len(value) > 253 or DNS_NAME.fullmatch(value) is None
            or value.endswith(('.localhost', '.local', '.test', '.internal', '.invalid', '.onion'))):
        raise DirectoryError('A public DNS hostname is required.')
    return value


def public_address(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        address = ipaddress.IPv4Address(value)
    except ValueError as exc:
        raise DirectoryError('A public IPv4 address is required.') from exc
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise DirectoryError('A public IPv4 address is required.')
    return str(address)


def master_url(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 300:
        raise DirectoryError('Invalid directory master URL.')
    try:
        parts = urlsplit(value)
        name = hostname(parts.hostname)
        port = 443 if parts.port is None else _integer(parts.port, 1, 65535)
    except ValueError as exc:
        raise DirectoryError('Invalid directory master URL.') from exc
    expected = 'https://' + name + (f':{port}' if port != 443 else '')
    if value != expected:
        raise DirectoryError('Directory masters must use canonical HTTPS origins.')
    return value


def signed_bytes(kind, payload):
    return b'phoenix-rising-directory-v1\0' + kind.encode('ascii') + b'\0' + canonical(payload)


def _verify(payload, signature, modulus):
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        # The Windows and Proton Starter bundles use the existing Windows CNG verifier.
        from starter_update_signing import verify
        return verify(payload, signature, modulus=modulus)
    key = rsa.RSAPublicNumbers(65537, int.from_bytes(modulus, 'big')).public_key()
    try:
        key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        return False


def _envelope(document):
    _fields(document, ('payload', 'signature'))
    if not isinstance(document['payload'], dict):
        raise DirectoryError('Invalid signed directory payload.')
    return document['payload']


def verify(document, kind, signer):
    payload = _envelope(document)
    modulus = public_key(signer)
    signature = _blob(document['signature'])
    try:
        if len(signature) != len(modulus) or not _verify(signed_bytes(kind, payload), signature, modulus):
            raise DirectoryError('Directory signature did not verify.')
    except (ValueError, OSError) as exc:
        raise DirectoryError('Directory signature did not verify.') from exc
    return payload


def _lifetime(payload, now, maximum, *, stale=0):
    issued = _integer(payload['issued_at'], 0, 2**53 - 1)
    expires = _integer(payload['expires_at'], issued + 1, issued + maximum)
    if issued > now + CLOCK_SKEW or expires <= now - stale:
        raise DirectoryError('Directory record is expired or from the future.')


def verify_trust(document, root, now, *, stale=0):
    payload = _envelope(document)
    _fields(payload, ('format', 'revision', 'issued_at', 'expires_at', 'masters', 'groups'))
    _integer(payload['format'], VERSION, VERSION)
    _integer(payload['revision'], 1, 2**53 - 1)
    _lifetime(payload, now, MAX_TRUST_AGE, stale=stale)
    masters, groups = payload['masters'], payload['groups']
    if not isinstance(masters, list) or not 1 <= len(masters) <= MAX_MASTERS:
        raise DirectoryError('Invalid directory master list.')
    if len({master_url(row) for row in masters}) != len(masters):
        raise DirectoryError('Repeated directory master.')
    if not isinstance(groups, list) or len(groups) > MAX_GROUPS:
        raise DirectoryError('Invalid directory trust groups.')
    seen = set()
    for group in groups:
        _fields(group, ('id', 'name', 'key'))
        _label(group['name'], 64)
        if _identity(group['id']) != key_id(group['key']) or group['id'] in seen:
            raise DirectoryError('Invalid directory group key.')
        seen.add(group['id'])
    return verify(document, 'trust', root)


def verify_revocations(document, group, now, *, stale=0):
    payload = _envelope(document)
    _fields(payload, ('format', 'revision', 'group_id', 'issued_at', 'expires_at', 'servers'))
    _integer(payload['format'], VERSION, VERSION)
    _integer(payload['revision'], 1, 2**53 - 1)
    _lifetime(payload, now, MAX_TRUST_AGE, stale=stale)
    servers = payload['servers']
    if payload['group_id'] != group['id'] or not isinstance(servers, list) or len(servers) > MAX_REVOKED:
        raise DirectoryError('Invalid group revocation list.')
    if len({_identity(value) for value in servers}) != len(servers):
        raise DirectoryError('Repeated revoked server.')
    return verify(document, 'revocations', group['key'])


def verify_membership(document, group, server_id, now):
    payload = _envelope(document)
    _fields(payload, ('format', 'group_id', 'server_id', 'role', 'issued_at', 'expires_at'))
    _integer(payload['format'], VERSION, VERSION)
    _lifetime(payload, now, MAX_TRUST_AGE)
    if payload['group_id'] != group['id'] or payload['server_id'] != server_id or payload['role'] not in ('regional', 'event', 'operator'):
        raise DirectoryError('Invalid directory group membership.')
    return verify(document, 'membership', group['key'])


def verify_heartbeat(document, now, *, stale=0):
    payload = _envelope(document)
    required = {'format', 'server_id', 'key', 'name', 'region', 'hostname', 'address', 'port', 'protocol',
                'version', 'mode', 'map', 'game_type', 'players', 'max_players', 'spectators', 'locked',
                'memberships', 'issued_at', 'expires_at'}
    if not required <= payload.keys() <= required | {'open_registration'}:
        raise DirectoryError('Invalid directory heartbeat fields.')
    if 'open_registration' in payload:
        registration = payload['open_registration']
        _fields(registration, ('udp_port',))
        _integer(registration['udp_port'], 1024, 65535)
    if len(canonical(document)) > MAX_HEARTBEAT:
        raise DirectoryError('Directory heartbeat is too large.')
    _integer(payload['format'], VERSION, VERSION)
    _lifetime(payload, now, HEARTBEAT_SECONDS, stale=stale)
    if _identity(payload['server_id']) != key_id(payload['key']):
        raise DirectoryError('Server identity does not match its key.')
    for field, limit in (('name', 80), ('region', 32), ('version', 32), ('map', 72), ('game_type', 24)):
        _label(payload[field], limit)
    hostname(payload['hostname'])
    public_address(payload['address'])
    _integer(payload['port'], 1, 65535)
    _integer(payload['protocol'], 1, 65535)
    _integer(payload['max_players'], 1, 128)
    _integer(payload['players'], 0, payload['max_players'])
    _integer(payload['spectators'], 0, 128)
    if payload['mode'] not in ('regional', 'event') or type(payload['locked']) is not bool:
        raise DirectoryError('Invalid server mode or lock state.')
    if not isinstance(payload['memberships'], list) or len(payload['memberships']) > 4:
        raise DirectoryError('Too many server memberships.')
    seen = set()
    for membership in payload['memberships']:
        claim = _envelope(membership)
        group_id = _identity(claim.get('group_id'))
        if group_id in seen:
            raise DirectoryError('Repeated server group.')
        seen.add(group_id)
    return verify(document, 'heartbeat', payload['key'])


def badges(payload, groups, revoked, now):
    """Reject a badge independently of the server's self-signed listing."""
    visible = []
    for membership in payload['memberships']:
        group_id = membership['payload']['group_id']
        group = groups.get(group_id)
        if group is None or payload['server_id'] in revoked.get(group_id, ()):
            continue
        try:
            claim = verify_membership(membership, group, payload['server_id'], now)
        except DirectoryError:
            continue
        visible.append({'id': group_id, 'name': group['name'], 'role': claim['role']})
    return visible



def feed_fields(feed):
    _fields(feed, ('format', 'trust', 'revocations', 'listings'))
    _integer(feed['format'], VERSION, VERSION)
    if (not isinstance(feed['revocations'], list) or len(feed['revocations']) > MAX_GROUPS
            or not isinstance(feed['listings'], list) or len(feed['listings']) > MAX_SERVERS):
        raise DirectoryError('Invalid directory list size.')
    return feed


class DirectoryIndex:
    """Merge independently verified records and discard expired live listings."""

    def __init__(self, root, trust, now, *, blocked=(), cached=False):
        self.root = root
        self.blocked = frozenset(_identity(key) for key in blocked)
        self.trust = trust
        self.trust_payload = verify_trust(trust, root, now, stale=CACHE_SECONDS if cached else 0)
        self.revocations = {}
        self.listings = {}

    def use_trust(self, document, now):
        trust = verify_trust(document, self.root, now)
        revision = self.trust_payload['revision']
        if trust['revision'] == revision and trust != self.trust_payload:
            raise DirectoryError('Conflicting signed directory trust revision.')
        if trust['revision'] > revision:
            self.trust, self.trust_payload = document, trust
            trusted_ids = {row['id'] for row in trust['groups']}
            self.revocations = {key: row for key, row in self.revocations.items() if key in trusted_ids}

    def publish(self, document, now, *, cached=False, permit=None):
        record = verify_heartbeat(document, now, stale=CACHE_SECONDS if cached else 0)
        server_id = record['server_id']
        if server_id in self.blocked:
            raise DirectoryError('Server is blocked by this directory.')
        if permit is not None:
            permit(server_id)
        self.expire(now, cached=cached)
        current = self.listings.get(server_id)
        if current is not None:
            old = current['payload']
            if old['issued_at'] == record['issued_at'] and old != record:
                raise DirectoryError('Conflicting signed server heartbeat.')
            if old['issued_at'] >= record['issued_at']:
                return False
        elif len(self.listings) >= MAX_SERVERS:
            raise DirectoryError('Directory has reached its listing capacity.')
        self.listings[server_id] = document
        return True

    def expire(self, now, *, cached=False):
        threshold = now - (CACHE_SECONDS if cached else 0)
        expired = [key for key, row in self.listings.items() if row['payload']['expires_at'] <= threshold]
        for key in expired:
            del self.listings[key]

    def absorb(self, feed, now, *, cached=False):
        feed_fields(feed)
        if not cached:
            self.use_trust(feed['trust'], now)
        trusted = {group['id']: group for group in self.trust_payload['groups']}
        for document in feed['revocations']:
            try:
                group = trusted[_identity(_envelope(document).get('group_id'))]
                revocation = verify_revocations(document, group, now, stale=CACHE_SECONDS if cached else 0)
            except (KeyError, DirectoryError):
                continue
            current = self.revocations.get(group['id'])
            if current is None or current['payload']['revision'] < revocation['revision']:
                self.revocations[group['id']] = document
        for document in feed['listings']:
            try:
                self.publish(document, now, cached=cached)
            except DirectoryError:
                continue

    def feed(self, now, *, cached=False):
        self.expire(now, cached=cached)
        return {'format': VERSION, 'trust': self.trust,
                'revocations': list(self.revocations.values()), 'listings': list(self.listings.values())}

    def rows(self, now, *, cached=False):
        self.expire(now, cached=cached)
        trust_live = self.trust_payload['expires_at'] > now
        groups = {group['id']: group for group in self.trust_payload['groups']
                  if group['id'] in self.revocations
                  and self.revocations[group['id']]['payload']['expires_at'] > now} if trust_live else {}
        revoked = {group: frozenset(row['payload']['servers']) for group, row in self.revocations.items()}
        rows = []
        for document in self.listings.values():
            payload = document['payload']
            live = payload['expires_at'] > now
            rows.append(dict(payload, live=live, badges=badges(payload, groups, revoked, now) if live else []))
        return sorted(rows, key=lambda row: (row['name'].casefold(), row['server_id']))
