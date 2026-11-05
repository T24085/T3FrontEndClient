"""Invite authentication and application-specific authenticated UDP transport.

No network listener starts on import. Native Unreal sockets remain loopback-only.
UDP payloads are authenticated, not encrypted; TLS protects credential delivery.
"""
import hashlib, hmac, ipaddress, json, os, pathlib, secrets, select, socket, struct, threading, time

MAGIC=b'T3D1'
MAX_PAYLOAD=65000

def write_json(path, value):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');os.replace(temp,path)

def read_json(path, limit=1024*1024):
    with pathlib.Path(path).open('rb') as f: data=f.read(limit+1)
    if len(data)>limit:raise ValueError('Configuration exceeds its size limit.')
    return json.loads(data)

def valid_public_address(value, *, local_test=False):
    address=ipaddress.IPv4Address(value)
    if not address.is_global and not (local_test and address.is_loopback):
        raise ValueError('Enter the public IPv4 address, not the VM LAN address.')
    return str(address)

class InviteStore:
    def __init__(self,path):
        self.path=pathlib.Path(path);self.lock=threading.RLock();self.last_read=0;self.records=[]
        if not self.path.exists():write_json(self.path,{'format':1,'players':[]})
        self.reload(force=True)

    def reload(self,force=False):
        with self.lock:
            if not force and time.monotonic()-self.last_read<1:return
            try:
                d=read_json(self.path)
                if set(d)!={'format','players'} or d['format']!=1 or not isinstance(d['players'],list) or len(d['players'])>256:raise ValueError('Invalid invitation registry.')
                seen=set()
                for r in d['players']:
                    if set(r)!={'id','label','token_hash','enabled'} or type(r['id'])is not int or not 1<=r['id']<=256 or r['id']in seen or type(r['enabled'])is not bool:raise ValueError('Invalid invitation registry.')
                    if not isinstance(r['token_hash'],str) or len(bytes.fromhex(r['token_hash']))!=32 or not isinstance(r['label'],str) or not 1<=len(r['label'])<=80:raise ValueError('Invalid invitation registry.')
                    seen.add(r['id'])
                self.records=d['players'];self.last_read=time.monotonic()
            except Exception:
                self.records=[];self.last_read=0;raise

    @staticmethod
    def address(identity):return '127.90.'+str(identity//250)+'.'+str(identity%250+2)

    def issue(self,label):
        with self.lock:
            self.reload(force=True)
            if not isinstance(label,str) or not 1<=len(label.strip())<=80:raise ValueError('Choose a player label.')
            used={r['id'] for r in self.records};identity=next((i for i in range(1,257)if i not in used),None)
            if identity is None:raise ValueError('Invitation registry is full; IDs are never reused.')
            token=secrets.token_urlsafe(32)
            self.records.append({'id':identity,'label':label.strip(),'token_hash':hashlib.sha256(token.encode()).hexdigest(),'enabled':True})
            write_json(self.path,{'format':1,'players':self.records});return identity,token

    def revoke(self,identity):
        with self.lock:
            self.reload(force=True)
            found=False
            for r in self.records:
                if r['id']==identity:r['enabled']=False;found=True
            if not found:raise ValueError('Invitation ID not found.')
            write_json(self.path,{'format':1,'players':self.records})

    def active(self,identity):
        try:
            self.reload()
            with self.lock:return any(r['id']==identity and r['enabled'] for r in self.records)
        except Exception:return False

    def authenticate(self,token):
        if not isinstance(token,str) or not 32<=len(token)<=128:raise ValueError('An invitation is required.')
        self.reload();actual=hashlib.sha256(token.encode('ascii')).hexdigest()
        with self.lock:
            for r in self.records:
                if hmac.compare_digest(actual,r['token_hash']) and r['enabled']:return r['id']
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
    def __init__(self,bind,public_port,native_port,permitted,*,clock=time.monotonic):
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
            if r is not None and r['expires']>time.time()+60 and r['session']==session:return self.public(r)
            if r is not None:
                r['socket'].close();del self.grants[old];self.identities.pop((match_id,peer_id),None)
            # A stopped lease must not retain sockets or consume capacity.
            self.prune()
            if len(self.grants)>=128:raise ValueError('UDP admission capacity reached.')
            ident=secrets.token_hex(16);key=secrets.token_bytes(32)
            upstream=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);upstream.bind((InviteStore.address(peer_id),0));upstream.connect(self.native)
            r={'id':ident,'key':key,'match':match_id,'peer':peer_id,'session':session,'expires':int(time.time())+7200,'socket':upstream,'remote':None,'window':ReplayWindow(),'sent':0}
            self.grants[ident]=r;self.identities[(match_id,peer_id)]=ident;return self.public(r)

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
                            if r is None or not self.permitted(r['match'],r['peer']):continue
                            payload=unframe(r['key'],r['id'],packet,b'C',r['window'])
                            if payload is None:continue
                            r['remote']=source;r['socket'].send(payload)
                    else:
                        payload=sock.recv(65535);r=upstreams[sock]
                        with self.lock:
                            if r['remote']and len(payload)<=MAX_PAYLOAD and self.permitted(r['match'],r['peer']):
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
        self.local=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.local.bind(('127.0.0.1',0));self.port=self.local.getsockname()[1]
        self.wire=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.wire.connect(self.remote);self.stop=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def run(self):
        while not self.stop.is_set()and time.time()<self.grant['expires']:
            try:
                ready,_,_=select.select([self.local,self.wire],[],[],.2)
                for sock in ready:
                    if sock is self.local:
                        payload,source=sock.recvfrom(65535)
                        if source[0]!='127.0.0.1' or (self.client is not None and source!=self.client)or len(payload)>MAX_PAYLOAD:continue
                        self.client=source;self.wire.send(frame(self.key,self.grant['id'],self.sent,payload,b'C'));self.sent+=1
                    else:
                        packet=sock.recv(65535);payload=unframe(self.key,self.grant['id'],packet,b'S',self.window)
                        if payload is not None and self.client:self.local.sendto(payload,self.client)
            except OSError:
                if self.stop.is_set():break

    def close(self):self.stop.set();self.thread.join(3);self.local.close();self.wire.close()
