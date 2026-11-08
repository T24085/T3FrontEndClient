"""Development desktop client for the direct-TLS community lobby.

This client has no hosting functionality. Match endpoint delivery is accepted
only from the authenticated TLS connection and checked against the client policy.
"""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading

from dynamic_destination import destination,isolated_source
from community_maps import BY_ID, read_options
from map_sync_contract import CATALOG_HEADER, CATALOG_VERSION


class CommunityError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class CommunityConnectionError(CommunityError):
    """The connection failed; a submitted operation may already have applied."""


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to the configured IP while validating TLS against its DNS name."""
    def __init__(self, hostname, port, address, *, context, timeout=10, source_address=None):
        super().__init__(hostname, port, timeout=timeout, context=context, source_address=source_address)
        self.pinned_address = address

    def connect(self):
        sock = socket.create_connection((self.pinned_address, self.port), self.timeout, self.source_address)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class CommunityClient:
    def __init__(self, hostname, port, server_address, policy, *, ssl_context=None, test_source=None):
        test_source=isolated_source(test_source)
        if not isinstance(hostname, str) or not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?', hostname):
            raise ValueError('Invalid lobby DNS name.')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid lobby port.')
        address = ipaddress.IPv4Address(server_address)
        if test_source is None:
            if address not in ipaddress.ip_network('100.64.0.0/10'):
                raise ValueError('Lobby server must use Tailscale IPv4.')
        elif str(address) != '127.0.0.1':
            raise ValueError('Invalid isolated test connection.')
        self.hostname = hostname.lower()
        self.port = port
        self.server_address = str(address)
        self.authority = self.hostname + ':' + str(port)
        self.origin = 'https://' + self.authority
        self.policy = policy
        self.test_source = test_source
        self.context = ssl_context if ssl_context is not None else ssl.create_default_context()
        if self.context.verify_mode != ssl.CERT_REQUIRED or not self.context.check_hostname:
            raise ValueError('TLS certificate and hostname validation are required.')
        self.code = None
        self.token = None
        self.player_id = None
        self._watch_tokens = {}
        self.server_maps = None
        self.lock = threading.RLock()

    def _request(self, path, data=None, *, spectator_token=None, use_lobby_token=True):
        headers = {'Host': self.authority, 'Accept': 'application/json', CATALOG_HEADER: str(CATALOG_VERSION)}
        method, body = 'GET', None
        if data is not None:
            method = 'POST'
            body = json.dumps(data, ensure_ascii=True).encode('utf-8')
            if len(body) > 4096:
                raise CommunityError('Request is too large.')
            headers.update({'Content-Type':'application/json', 'Origin':self.origin})
            if self.token and use_lobby_token:
                headers['X-Lobby-Token'] = self.token
            if spectator_token is not None:
                headers['X-Spectator-Token']=spectator_token
        source = (self.test_source, 0) if self.test_source else None
        # Starting revalidates the whole roster before allocating a match.
        # Give that bounded operation longer than ordinary lobby requests.
        timeout = 30 if path == 'start' else 10
        conn = PinnedHTTPSConnection(self.hostname, self.port, self.server_address, context=self.context,
                                     timeout=timeout, source_address=source)
        try:
            conn.request(method, '/api/' + path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read(65537)
            if len(raw) > 65536 or response.getheader('Content-Type', '').split(';', 1)[0] != 'application/json':
                raise CommunityError('Invalid lobby response.')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CommunityError('Invalid lobby response.')
            if response.status != 200:
                code = value.get('code')
                if code not in ('lobby_missing', 'session_invalid','spectator_session_invalid',
                                'spectator_unavailable','spectator_forbidden','spectator_conflict','spectator_capacity'): code = None
                raise CommunityError(str(value.get('error', 'Lobby request failed.'))[:256], code=code)
            return value
        except CommunityError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise CommunityConnectionError('Could not securely contact the community lobby.') from exc
        except ValueError as exc:
            raise CommunityError('Invalid lobby response.') from exc
        finally:
            conn.close()

    def capabilities(self):
        with self.lock:
            caps = self._request('capabilities')
            try:
                self.server_maps = (read_options(caps['maps'], dynamic=True)
                                    if caps.get('mapFileSync') == CATALOG_VERSION else None)
            except (ValueError, KeyError) as exc:
                raise CommunityError('Invalid server map catalog.') from exc
            return caps

    def map_label(self, name):
        if not isinstance(name, str):
            return None
        if self.server_maps is not None:
            return self.server_maps.get(name)
        return BY_ID[name].label if name in BY_ID else None

    def create(self, name):
        with self.lock:
            if self.code is not None:
                try:
                    return self.action('state')
                except CommunityError as exc:
                    if exc.code not in ('lobby_missing', 'session_invalid'):
                        raise
            return self._remember(self._request('create', {'name':name}))

    def join(self, code, name):
        with self.lock:
            if self.code is not None and self.code != code:
                try:
                    self.action('state')
                except CommunityError as exc:
                    if exc.code not in ('lobby_missing', 'session_invalid'):
                        raise
                else:
                    raise CommunityError('Leave lobby '+self.code+' before joining another lobby.')
            return self._remember(self._request('join', {'code':code, 'name':name}))

    def resume(self):
        """Recover only this freshly verified device's existing membership."""
        with self.lock:
            response = self._request('resume', {})
            if response.get('room') is None and set(response) == {'room'}:
                self.code = self.token = self.player_id = None
                return None
            return self._remember(response)

    def _remember(self, response):
        room, token = response.get('room'), response.get('token')
        if (not isinstance(room, dict) or not isinstance(room.get('code'), str)
                or not re.fullmatch(r'[A-Z2-9]{6}', room['code'])
                or not isinstance(room.get('playerId'), str)
                or not isinstance(token, str) or not token.isascii() or not 16 <= len(token) <= 128):
            raise CommunityError('Invalid lobby session response.')
        self.code, self.token, self.player_id = room['code'], token, room['playerId']
        return room

    def action(self, operation, **data):
        with self.lock:
            if self.code is None or operation not in ('state', 'team', 'map', 'start', 'stop', 'reset', 'leave','spectators'):
                raise CommunityError('No valid lobby action is available.')
            if 'code' in data:
                raise CommunityError('Invalid lobby action.')
            try:
                result = self._request(operation, {'code':self.code, **data})
            except CommunityError as exc:
                if exc.code in ('lobby_missing', 'session_invalid'):
                    self.code = self.token = self.player_id = None
                raise
            if operation == 'leave':
                if result.get('left') is not True:
                    raise CommunityError('Invalid leave response.')
                self.code = self.token = self.player_id = None
                return None
            room = result.get('room')
            if not isinstance(room, dict) or room.get('code') != self.code or room.get('playerId') != self.player_id:
                raise CommunityError('Lobby response does not match this session.')
            return room

    def match_endpoint(self):
        """Read a fresh server state and validate its allocated game endpoint."""
        return self.match_target()['endpoint']

    def match_target(self):
        """Require a fresh endpoint and the selected map's content fingerprint."""
        with self.lock:
            room = self.action('state')
            match = room.get('match')
            if room.get('phase') != 'ready' or not isinstance(match,dict) or match.get('status') != 'ready':
                raise CommunityError('The match is not ready yet.')
            return self._validated_target(match,room.get('map'))

    def _validated_target(self,match,name,*,spectator=False):
        if not isinstance(match,dict):raise CommunityError('Invalid match response.')
        if match.get('map', name) != name:
            raise CommunityError('The allocated match does not match the selected map.')
        fingerprint,match_id=match.get('contentHash'),match.get('id')
        pattern=r'[0-9a-f]{32}' if spectator else r'[A-Za-z0-9_-]{1,64}'
        if not isinstance(match_id,str) or not re.fullmatch(pattern,match_id):
            raise CommunityError('The server did not provide a valid match identity.')
        if self.map_label(name) is None or not isinstance(fingerprint,str) or not re.fullmatch(r'[0-9a-f]{64}',fingerprint):
            raise CommunityError('The server did not provide a valid map version.')
        if spectator and match.get('role')!='spectator':
            raise CommunityError('The server did not provide an observer admission.')
        address,port=match.get('address'),match.get('port')
        if not isinstance(address,str) or type(port)is not int:
            raise CommunityError('The match endpoint is unavailable.')
        try:endpoint=destination(address+':'+str(port),self.policy,test_source=self.test_source)
        except ValueError as exc:raise CommunityError('The match endpoint is not approved by this client.')from exc
        target={'endpoint':endpoint,'map':name,'contentHash':fingerprint,'matchId':match_id}
        if spectator:target['role']='spectator'
        return target

    def live_matches(self):
        with self.lock:
            value=self._request('matches',use_lobby_token=False)
            matches=value.get('matches')
            if not isinstance(matches,list):raise CommunityError('Invalid live match list.')
            seen=set();result=[]
            fields={'id','map','label','playerCount','playerCapacity','spectatorCount','spectatorCapacity','canSpectate'}
            for item in matches:
                if (not isinstance(item,dict) or set(item)!=fields or not isinstance(item['id'],str)
                        or re.fullmatch('[0-9a-f]{32}',item['id'])is None or item['id']in seen
                        or self.map_label(item['map']) is None or item['label']!=self.map_label(item['map'])
                        or type(item['canSpectate'])is not bool
                        or any(type(item[k])is not int or item[k]<0 for k in
                               ('playerCount','playerCapacity','spectatorCount','spectatorCapacity'))
                        or item['playerCount']>item['playerCapacity']):
                    raise CommunityError('Invalid live match list.')
                seen.add(item['id']);result.append(dict(item))
            # _request's existing64KiB wire bound limits the whole projection.
            return result

    def _watch_response(self,value,*,expected_watch_id=None):
        watch=value.get('watch')
        if not isinstance(watch,dict) or set(watch)!={'watchId','token','match'}:
            raise CommunityError('Invalid observer session response.')
        watch_id,token=watch['watchId'],watch['token']
        if (not isinstance(watch_id,str) or re.fullmatch('[A-Za-z0-9_-]{16,64}',watch_id)is None
                or not isinstance(token,str) or not token.isascii() or not 32<=len(token)<=128
                or (expected_watch_id is not None and (watch_id!=expected_watch_id or token!=self._watch_tokens.get(watch_id)))):
            raise CommunityError('Invalid observer session response.')
        match=watch['match']
        target=self._validated_target(match,match.get('map')if isinstance(match,dict)else None,spectator=True)
        target['watchId']=watch_id
        return watch_id,token,target

    def spectate(self,match_id,name):
        with self.lock:
            if self._watch_tokens:raise CommunityError('Stop watching the current match first.')
            value=self._request('spectate',{'matchId':match_id,'name':name},use_lobby_token=False)
            watch_id,token,target=self._watch_response(value)
            if target['matchId']!=match_id:raise CommunityError('Observer admission belongs to another match.')
            self._watch_tokens[watch_id]=token
            return target

    def spectator_target(self,watch_id):
        with self.lock:
            token=self._watch_tokens.get(watch_id)
            if token is None:raise CommunityError('No observer session is available.','spectator_session_invalid')
            try:
                value=self._request('spectator-state',{'watchId':watch_id},spectator_token=token,use_lobby_token=False)
            except CommunityError as exc:
                if exc.code=='spectator_session_invalid':self._watch_tokens.pop(watch_id,None)
                raise
            return self._watch_response(value,expected_watch_id=watch_id)[2]

    def release_spectator(self,watch_id):
        with self.lock:
            token=self._watch_tokens.get(watch_id)
            if token is None:return False
            try:
                value=self._request('spectator-release',{'watchId':watch_id},spectator_token=token,use_lobby_token=False)
            except CommunityError as exc:
                if exc.code=='spectator_session_invalid':self._watch_tokens.pop(watch_id,None)
                raise
            if value.get('released')is not True or value.get('watchId')!=watch_id:
                raise CommunityError('Invalid observer release response.')
            self._watch_tokens.pop(watch_id,None)
            return True
