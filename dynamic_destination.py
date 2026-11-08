"""Validate a development match destination before starting a client."""
import ipaddress

ISOLATED_TEST_SOURCES=('127.0.0.2','127.0.0.3','127.0.0.4')


DIRECT_BRIDGE_POLICY = {'transport': 'authenticated-udp-v1', 'server_address': '127.0.0.1',
                        'first_port': 1024, 'last_port': 65535}


def isolated_source(value):
    """The three explicit devices in a player/player/observer loopback test."""
    if value is not None and (not isinstance(value,str) or value not in ISOLATED_TEST_SOURCES):
        raise ValueError('Invalid isolated test source.')
    return value


def destination(value, policy, *, test_source=None):
    test_source=isolated_source(test_source)
    if not isinstance(value, str):
        raise ValueError('A match address is required.')
    host, separator, port_text = value.rpartition(':')
    if not separator or not port_text.isascii() or not port_text.isdigit():
        raise ValueError('Invalid match address.')
    try:
        address, port = ipaddress.IPv4Address(host), int(port_text)
    except ValueError as exc:
        raise ValueError('Invalid match address.') from exc
    if policy == DIRECT_BRIDGE_POLICY:
        if str(address) != '127.0.0.1' or not 1024 <= port <= 65535:
            raise ValueError('Direct-host native traffic must use the local UDP bridge.')
        return str(address) + ':' + str(port)
    if not isinstance(policy, dict) or set(policy) != {'server_address', 'first_port', 'last_port'}:
        raise ValueError('Invalid match connection policy.')
    try:
        server = ipaddress.IPv4Address(policy['server_address'])
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid server address.') from exc
    if server not in ipaddress.ip_network('100.64.0.0/10'):
        raise ValueError('The community server must use Tailscale IPv4.')
    first, last = policy['first_port'], policy['last_port']
    if type(first) is not int or type(last) is not int or not 1024 <= first <= last <= 65535:
        raise ValueError('Invalid match port range.')
    if test_source is not None:
        if str(address) != '127.0.0.1':
            raise ValueError('Invalid isolated test endpoint.')
    elif address != server:
        raise ValueError('Match address does not match the configured community server.')
    if not first <= port <= last:
        raise ValueError('Match port is outside the configured range.')
    return str(address) + ':' + str(port)
