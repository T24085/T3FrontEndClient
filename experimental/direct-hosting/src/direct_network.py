"""Invite authentication and application-specific authenticated UDP transport.

No network listener starts on import. Native Unreal sockets remain loopback-only.
UDP payloads are authenticated, not encrypted; TLS protects credential delivery.
"""
from contextlib import contextmanager
import hashlib, hmac, ipaddress, json, os, pathlib, re, secrets, select, socket, struct, threading, time

MAGIC=b'T3D1'
MAX_PAYLOAD=65000
MAX_DEVICES=2048
MATCH_SLOT_LIMIT = 10
LEGACY_MATCH_UDP_BASE = 18000
MATCH_UDP_BASE = 18443
MATCH_UDP_BASES = (LEGACY_MATCH_UDP_BASE, MATCH_UDP_BASE)
GROUP_FILE='group-invitation.json'
ENROLL_ROUTE='/api/direct-enroll'
TOKEN=re.compile(r'[A-Za-z0-9_-]{43}')
ENDPOINT_FIELDS={'hostname','public_address','https_port','first_udp_port','last_udp_port'}
VOICE_ROUTE = '/api/proximity-voice'
VOICE_PROTOCOL = 't3-proximity-pcm-v1'
VOICE_SAMPLE_RATE = 16000
VOICE_FRAME_BYTES = VOICE_SAMPLE_RATE * 2 // 50
VOICE_KEEPALIVE = b'\x00'
VOICE_AUDIO = b'\x01'
VOICE_RELEASE = b'\x02'


class VoiceFrames:
    """Decode fixed-size PCM records and single-byte controls over TLS."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, raw):
        self.buffer.extend(raw)
        records = []
        cursor = 0
        while cursor < len(self.buffer):
            kind = bytes(self.buffer[cursor:cursor+1])
            if kind not in (VOICE_KEEPALIVE, VOICE_AUDIO, VOICE_RELEASE):
                raise ValueError('Invalid proximity voice frame.')
            end = cursor + 1 + (VOICE_FRAME_BYTES if kind == VOICE_AUDIO else 0)
            if end > len(self.buffer):
                break
            records.append((kind, bytes(self.buffer[cursor+1:end])))
            cursor = end
        del self.buffer[:cursor]
        return records

def write_json(path, value):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
        for attempt in range(10):
            try:
                os.replace(temp,path)
                break
            except PermissionError:
                if os.name!='nt' or attempt==9:raise
                time.sleep(.02)
    finally:
        temp.unlink(missing_ok=True)

def read_json(path, limit=4*1024*1024):
    with pathlib.Path(path).open('rb') as f: data=f.read(limit+1)
    if len(data)>limit:raise ValueError('Configuration exceeds its size limit.')
    return json.loads(data)

@contextmanager
def locked_state(path):
    path=pathlib.Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_name(path.name+'.lock').open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
        yield

def valid_public_address(value, *, local_test=False):
    address=ipaddress.IPv4Address(value)
    if (not address.is_global or address.is_multicast) and not (local_test and address.is_loopback):
        raise ValueError('Enter a public IPv4 address.')
    return str(address)

def validate_endpoint(data, *, local_test=False):
    valid_public_address(data['public_address'],local_test=local_test)
    name=data['hostname']
    if not isinstance(name,str) or not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?',name):
        raise ValueError('Invalid public lobby hostname.')
    port=data['https_port']
    if type(port) is not int or not 1<=port<=65535:
        raise ValueError('Invalid HTTPS port.')
    first,last=data['first_udp_port'],data['last_udp_port']
    if type(first) is not int or type(last) is not int or not 1024<=first<=last<=65535:
        raise ValueError('Invalid UDP range.')
    return {field:data[field] for field in ENDPOINT_FIELDS}

def validate_group(data, *, local_test=False):
    if (not isinstance(data,dict) or set(data)!=ENDPOINT_FIELDS|{'format','host_id','enrollment_token'}
            or type(data['format']) is not int or data['format']!=1
            or not isinstance(data['host_id'],str) or not re.fullmatch(r'[0-9a-f]{32}',data['host_id'])
            or not isinstance(data['enrollment_token'],str) or not TOKEN.fullmatch(data['enrollment_token'])):
        raise ValueError('This Starter has an invalid group invitation.')
    validate_endpoint(data,local_test=local_test)
    return data

class InviteStore:
    def __init__(self,path):
        self.path=pathlib.Path(path);self.lock=threading.RLock();self.last_read=0;self.records=[]
        if not self.path.exists():
            with locked_state(self.path):
                if not self.path.exists():write_json(self.path,{'format':1,'players':[]})
        self.reload(force=True)

    def reload(self,force=False):
        with self.lock:
            if not force and time.monotonic()-self.last_read<1:return
            try:
                d=read_json(self.path)
                if set(d)!={'format','players'} or d['format']!=1 or not isinstance(d['players'],list) or len(d['players'])>MAX_DEVICES:raise ValueError('Invalid invitation registry.')
                by_id={}
                by_token={}
                for r in d['players']:
                    if set(r)!={'id','label','token_hash','enabled'} or type(r['id'])is not int or not 1<=r['id']<=MAX_DEVICES or r['id']in by_id or type(r['enabled'])is not bool:raise ValueError('Invalid invitation registry.')
                    digest=r['token_hash']
                    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or digest in by_token or not isinstance(r['label'],str) or not 1<=len(r['label'])<=80:raise ValueError('Invalid invitation registry.')
                    by_id[r['id']]=r
                    by_token[digest]=r
                self.records=d['players'];self.by_id=by_id;self.by_token=by_token;self.last_read=time.monotonic()
            except Exception:
                self.records=[];self.by_id={};self.by_token={};self.last_read=0;raise

    @staticmethod
    def address(identity):return '127.90.'+str(identity//250)+'.'+str(identity%250+2)

    def issue(self,label):
        token=secrets.token_urlsafe(32)
        return self.register(token,label),token

    def register(self,token,label):
        if not isinstance(token,str) or not TOKEN.fullmatch(token):
            raise ValueError('Invalid device credential.')
        if not isinstance(label,str) or not 1<=len(label.strip())<=80:
            raise ValueError('Choose a player label.')
        digest=hashlib.sha256(token.encode('ascii')).hexdigest()
        with self.lock, locked_state(self.path):
            self.reload(force=True)
            existing=self.by_token.get(digest)
            if existing is not None:
                if not existing['enabled']:raise PermissionError('This device was revoked.')
                return existing['id']
            identity=next((i for i in range(1,MAX_DEVICES+1) if i not in self.by_id),None)
            if identity is None:raise OverflowError('The host device registry is full.')
            row={'id':identity,'label':label.strip(),'token_hash':digest,'enabled':True}
            write_json(self.path,{'format':1,'players':self.records+[row]})
            self.records.append(row)
            self.by_id[identity]=self.by_token[digest]=row
            return identity

    def revoke(self,identity):
        with self.lock, locked_state(self.path):
            self.reload(force=True)
            if identity not in self.by_id:raise ValueError('Invitation ID not found.')
            updated=[dict(row,enabled=False) if row['id']==identity else row for row in self.records]
            write_json(self.path,{'format':1,'players':updated})
            self.reload(force=True)

    def active(self,identity):
        try:
            self.reload()
            with self.lock:return self.by_id.get(identity,{}).get('enabled',False)
        except Exception:return False

    def authenticate(self,token):
        if not isinstance(token,str) or not 32<=len(token)<=128:raise ValueError('An invitation is required.')
        self.reload();actual=hashlib.sha256(token.encode('ascii')).hexdigest()
        with self.lock:
            row=self.by_token.get(actual)
            if row is not None and row['enabled']:return row['id']
        raise ValueError('Invitation is invalid or revoked.')

    def peer(self,identity):
        from tailnet_identity import Peer
        if not self.active(identity):raise ValueError('Invitation is revoked.')
        return Peer(self.address(identity),'direct-device-'+str(identity),identity)

    def resolve(self,address):
        self.reload()
        with self.lock:
            identity=next((r['id']for r in self.records if self.address(r['id'])==address and r['enabled']),None)
        if identity is None:raise ValueError('Invitation is revoked.')
        return self.peer(identity)

class ReplayWindow:
    def __init__(self):self.high=-1;self.bits=0
    def accept(self,sequence):
        if sequence>self.high:
            shift=sequence-self.high;self.bits=((self.bits<<shift)|1)&((1<<256)-1) if shift<256 else 1;self.high=sequence;return True
        age=self.high-sequence
        if age>=256 or self.bits&(1<<age):return False
        self.bits|=1<<age;return True

def frame(key,identity,sequence,payload,direction):
    if len(payload)>MAX_PAYLOAD:raise ValueError('UDP datagram exceeds transport limit.')
    head=MAGIC+bytes.fromhex(identity)+struct.pack('!Q',sequence)+payload
    return head+hmac.digest(key,direction+head,'sha256')

def unframe(key,identity,packet,direction,window):
    if not 60<=len(packet)<=MAX_PAYLOAD+60 or packet[:4]!=MAGIC or packet[4:20]!=bytes.fromhex(identity):return None
    if not hmac.compare_digest(hmac.digest(key,direction+packet[:-32],'sha256'),packet[-32:]):return None
    sequence=struct.unpack('!Q',packet[20:28])[0]
    if not window.accept(sequence):return None
    return packet[28:-32]

class UdpServer:
    def __init__(self,bind,public_port,native_port,permitted,*,clock=time.monotonic,forward=None,renew=False,route=None):
        self.forward = forward if forward is not None else permitted
        self.renew = renew
        self.route = route
        self.clock=clock;self.permitted=permitted;self.native=('127.0.0.1',native_port);self.public_port=public_port
        self.lock=threading.RLock();self.stop=threading.Event();self.grants={};self.identities={}
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        self.socket.bind((bind,public_port));self.public_port=self.socket.getsockname()[1]
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def grant(self,match_id,peer_id,session=''):
        if not self.permitted(match_id,peer_id):raise ValueError('No live match admission exists.')
        with self.lock:
            old=self.identities.get((match_id,peer_id));r=self.grants.get(old)
            if r is not None and r['session']==session:
                now = int(time.time())
                renewable = self.renew(match_id) if callable(self.renew) else self.renew
                if renewable and now < r['expires'] <= now+600:
                    r['expires'] = now+7200
                if r['expires']>now+60:
                    return self.public(r)
            if r is not None:
                r['socket'].close();del self.grants[old];self.identities.pop((match_id,peer_id),None)
            # A stopped lease must not retain sockets or consume capacity.
            self.prune()
            if len(self.grants)>=128:raise ValueError('UDP admission capacity reached.')
            ident=secrets.token_hex(16);key=secrets.token_bytes(32)
            native = ('127.0.0.1', self.route(match_id)) if self.route is not None else self.native
            upstream=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);upstream.bind((InviteStore.address(peer_id),0));upstream.connect(native)
            r={'id':ident,'key':key,'match':match_id,'peer':peer_id,'session':session,'expires':int(time.time())+7200,'socket':upstream,'remote':None,'window':ReplayWindow(),'sent':0}
            self.grants[ident]=r;self.identities[(match_id,peer_id)]=ident;return self.public(r)

    def voice_admitted(self, match_id, peer_id, session, grant_id):
        with self.lock:
            grant = self.grants.get(grant_id)
            return bool(grant and self.identities.get((match_id, peer_id)) == grant_id
                        and grant['session'] == session and grant['expires'] > time.time())

    def public(self,r):return {'id':r['id'],'key':r['key'].hex(),'matchId':r['match'],'expires':r['expires'],'port':self.public_port}

    def prune(self):
        with self.lock:
            for identity,r in list(self.grants.items()):
                if r['expires']<=time.time() or not self.permitted(r['match'],r['peer']):
                    r['socket'].close();del self.grants[identity];self.identities.pop((r['match'],r['peer']),None)

    def run(self):
        while not self.stop.is_set():
            try:
                self.prune()
                with self.lock:upstreams={r['socket']:r for r in self.grants.values()}
                readable,_,_=select.select([self.socket]+list(upstreams),[],[],.2)
                for sock in readable:
                    if sock is self.socket:
                        packet,source=sock.recvfrom(65535)
                        if len(packet)<60 or packet[:4]!=MAGIC:continue
                        with self.lock:
                            r=self.grants.get(packet[4:20].hex())
                            if r is None or not self.forward(r['match'],r['peer']):continue
                            payload=unframe(r['key'],r['id'],packet,b'C',r['window'])
                            if payload is None:continue
                            r['remote']=source;r['socket'].send(payload)
                    else:
                        payload=sock.recv(65535);r=upstreams[sock]
                        with self.lock:
                            if r['remote']and len(payload)<=MAX_PAYLOAD and self.forward(r['match'],r['peer']):
                                self.socket.sendto(frame(r['key'],r['id'],r['sent'],payload,b'S'),r['remote']);r['sent']+=1
            except (OSError,ValueError):
                if self.stop.is_set():break

    def close(self):
        self.stop.set();self.thread.join(3)
        with self.lock:
            for r in self.grants.values():r['socket'].close()
            self.grants.clear();self.identities.clear()
        self.socket.close()

class UdpClient:
    def __init__(self,address,grant):
        if set(grant)!={'id','key','matchId','expires','port'}:raise ValueError('Invalid UDP grant fields.')
        if len(bytes.fromhex(grant['id']))!=16 or len(bytes.fromhex(grant['key']))!=32 or type(grant['port'])is not int or not 1024<=grant['port']<=65535:raise ValueError('Invalid UDP grant.')
        if type(grant['expires'])is not int or not time.time()<grant['expires']<=time.time()+7201:raise ValueError('Invalid UDP grant deadline.')
        self.grant=dict(grant);self.key=bytes.fromhex(grant['key']);self.window=ReplayWindow();self.sent=0;self.remote=(str(ipaddress.IPv4Address(address)),grant['port']);self.client=None
        self.rebind_until=0
        self.local=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.local.bind(('127.0.0.1',0));self.port=self.local.getsockname()[1]
        self.wire=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.wire.connect(self.remote);self.stop=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def run(self):
        while not self.stop.is_set()and time.time()<self.grant['expires']:
            try:
                ready,_,_=select.select([self.local,self.wire],[],[],.2)
                for sock in ready:
                    if sock is self.local:
                        payload,source=sock.recvfrom(65535)
                        if source[0]!='127.0.0.1' or len(payload)>MAX_PAYLOAD:continue
                        if self.client is not None and source != self.client:
                            if time.monotonic() >= self.rebind_until:
                                continue
                            self.rebind_until = 0
                        self.client=source;self.wire.send(frame(self.key,self.grant['id'],self.sent,payload,b'C'));self.sent+=1
                    else:
                        packet=sock.recv(65535);payload=unframe(self.key,self.grant['id'],packet,b'S',self.window)
                        if payload is not None and self.client:self.local.sendto(payload,self.client)
            except OSError:
                if self.stop.is_set():break

    def renew(self, grant):
        previous = self.grant
        expiry = grant.get('expires')
        if (type(expiry) is not int or not previous['expires'] <= expiry <= time.time()+7201
                or dict(grant, expires=previous['expires']) != previous):
            raise ValueError('Invalid public UDP renewal.')
        self.grant = dict(grant)

    def allow_rebind(self):
        # A public map transition replaces Unreal's local net driver and its
        # ephemeral port. Keep the proxy port and authenticated grant stable.
        self.rebind_until = time.monotonic() + 180

    def close(self):self.stop.set();self.thread.join(3);self.local.close();self.wire.close()
