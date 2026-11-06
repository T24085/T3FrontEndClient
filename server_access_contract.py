"""Small server-sharing bootstrap contract; no lobby or game permissions."""
import re
from urllib.parse import urlsplit

CONTRACT = 'tailscale-server-access-v1'
INVITE_PATH = '/v1/server-access'
MAX_RESPONSE = 4096


def invite_url(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'https://login\.tailscale\.com/admin/invite/[A-Za-z0-9_-]{8,256}', value):
        raise ValueError('Invalid Tailscale server invitation.')
    return value


def endpoint_url(value):
    if not isinstance(value, str) or len(value) > 1024:
        raise ValueError('Invalid server-access endpoint.')
    parts = urlsplit(value)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path != INVITE_PATH
            or not re.fullmatch(r'[A-Za-z0-9.-]+', parts.hostname)):
        raise ValueError('Server access requires an HTTPS setup endpoint.')
    if parts.port not in (None, 443, 8443, 10000):
        raise ValueError('Invalid server-access port.')
    return value


def enrollment_code(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', value):
        raise ValueError('Invalid server-access enrollment code.')
    return value
