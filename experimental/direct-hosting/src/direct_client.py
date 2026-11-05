"""Separate direct-host Starter entry; credentials stay outside the package."""
import ipaddress, json, os, pathlib, re, ssl, sys, secrets
from direct_network import UdpClient,read_json,write_json,valid_public_address
from community_transport import CommunityClient,CommunityError

ROOT=pathlib.Path(__file__).resolve().parent

def validate_connection(d,*,local_test=False):
    if not isinstance(d,dict)or set(d)!={'format','hostname','public_address','https_port','first_udp_port','last_udp_port','access_token'}or d['format']!=1:raise ValueError('Choose an invitation exported by the direct host.')
    valid_public_address(d['public_address'],local_test=local_test)
    if not isinstance(d['hostname'],str)or not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?',d['hostname']):raise ValueError('Invalid public lobby hostname.')
    if type(d['https_port'])is not int or not 1<=d['https_port']<=65535:raise ValueError('Invalid HTTPS port.')
    if any(type(d[k])is not int for k in ('first_udp_port','last_udp_port'))or not 1024<=d['first_udp_port']<=d['last_udp_port']<=65535:raise ValueError('Invalid UDP range.')
    if not isinstance(d['access_token'],str)or re.fullmatch(r'[A-Za-z0-9_-]{43}',d['access_token'])is None:raise ValueError('Invalid invitation credential.')
    return dict(d)

class DirectClient(CommunityClient):
    def __init__(self,connection,*,ssl_context=None,test_source=None):
        d=validate_connection(connection,local_test=test_source is not None)
        policy={'transport':'authenticated-udp-v1','server_address':'127.0.0.1','first_port':1024,'last_port':65535}
        super().__init__(d['hostname'],d['https_port'],d['public_address'],policy,ssl_context=ssl_context,test_source=test_source)
        self.connection=d;self.access_token=d['access_token'];self.direct_session=secrets.token_hex(16);self.proxies={}

    def _validated_target(self,match,name,*,spectator=False):
        from community_maps import BY_ID
        if not isinstance(match,dict)or match.get('address')!=self.server_address or type(match.get('port'))is not int or not self.connection['first_udp_port']<=match['port']<=self.connection['last_udp_port']:raise CommunityError('The public match endpoint differs from this invitation.')
        grant=match.get('udpGrant')
        if name not in BY_ID or re.fullmatch('[0-9a-f]{64}',match.get('contentHash',''))is None or not isinstance(grant,dict)or grant.get('matchId')!=match.get('id')or grant.get('port')!=match['port']:raise CommunityError('The host did not provide this match admission. Wait for Start match, or request a fresh invitation.')
        key=(grant.get('matchId'),grant.get('id'))
        with self.lock:
            proxy=self.proxies.get(key)
            if proxy is not None and proxy.grant!=grant:raise CommunityError('UDP admission changed without a new identity.')
            if proxy is None:
                # One native session at a time is already enforced by CommunityGame.
                for old in self.proxies.values():old.close()
                self.proxies.clear()
                try:proxy=UdpClient(self.server_address,grant)
                except (ValueError,OSError)as exc:raise CommunityError('UDP match admission could not be opened.')from exc
                self.proxies[key]=proxy
            native=dict(match,address='127.0.0.1',port=proxy.port)
            return super()._validated_target(native,name,spectator=spectator)

    def close(self):
        with self.lock:
            for proxy in self.proxies.values():proxy.close()
            self.proxies.clear()

def main():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    from desktop_launcher import Desktop
    from community_game import CommunityGame
    from startup_paths import installation_options
    from client_support import discover_game
    from steam_identity import read_steam_name
    local=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'Tribes3DirectStarter'
    local.mkdir(parents=True,exist_ok=True);saved=local/'connection.json'
    chooser=tk.Tk();chooser.withdraw()
    try:
        if not saved.exists():
            filename=filedialog.askopenfilename(title='Choose the player invitation JSON sent by your host',filetypes=[('Player invitation','*.json')])
            if not filename:return
            write_json(saved,validate_connection(read_json(filename,16384)))
        connection=validate_connection(read_json(saved,16384))
        game,workspace=installation_options();source=discover_game(game)
        lobby=DirectClient(connection)
        try:lobby.capabilities()
        except CommunityError:
            messagebox.showerror('Direct host connection','Cannot contact the host with this invitation. Check the hostname, certificate, public IP, forwarded ports and invitation revocation. To import a different host, use Change Host Invitation.vbs.');return
    except Exception as exc:
        messagebox.showerror('Direct Starter setup',str(exc));return
    finally:chooser.destroy()
    class DirectDesktop(Desktop):
        def close(self):
            try:super().close()
            finally:lobby.close()
    root=tk.Tk();root.title('TRIBES 3 — Direct Host Starter — private candidate')
    factory=lambda current:CommunityGame(current,ROOT,source,workspace,workspace/'direct-desktop-control')
    gui=DirectDesktop(root,lobby,factory,steam_name_loader=lambda:read_steam_name(source,ROOT/'base-game-manifest.json'))
    root.protocol('WM_DELETE_WINDOW',gui.close)
    try:root.mainloop()
    finally:lobby.close()

def change_invitation():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    try:
        filename=filedialog.askopenfilename(title='Choose the new player invitation',filetypes=[('Player invitation','*.json')])
        if filename:
            d=validate_connection(read_json(filename,16384));p=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'Tribes3DirectStarter/connection.json'
            if p.exists():p.with_suffix('.previous.json').write_bytes(p.read_bytes())
            write_json(p,d);messagebox.showinfo('Invitation saved','Close any other Direct Starter window, then reopen Direct Starter.')
    except Exception as exc:messagebox.showerror('Invitation',str(exc))
    finally:root.destroy()

if __name__=='__main__':main()
