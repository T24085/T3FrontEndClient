"""Separate direct-host Starter entry; credentials stay outside the package."""
import os, pathlib, re, secrets
from direct_network import UdpClient,read_json,write_json,valid_public_address
from community_transport import CommunityClient,CommunityError
from dynamic_destination import DIRECT_BRIDGE_POLICY

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
    address_error = 'A direct host must have a public IPv4 address.'

    @staticmethod
    def accepts_server_address(address):
        return address.is_global and not address.is_multicast

    def __init__(self,connection,*,ssl_context=None,test_source=None):
        d=validate_connection(connection,local_test=test_source is not None)
        super().__init__(d['hostname'],d['https_port'],d['public_address'],dict(DIRECT_BRIDGE_POLICY),
                         ssl_context=ssl_context,test_source=test_source)
        self.connection=d;self.access_token=d['access_token'];self.direct_session=secrets.token_hex(16);self.proxies={}

    def request_headers(self):
        return dict(super().request_headers(), **{
            'Authorization': 'Bearer ' + self.access_token,
            'X-Direct-Session': self.direct_session,
        })

    def _validated_target(self,match,name,*,spectator=False):
        if not isinstance(match,dict)or match.get('address')!=self.server_address or type(match.get('port'))is not int or not self.connection['first_udp_port']<=match['port']<=self.connection['last_udp_port']:raise CommunityError('The public match endpoint differs from this invitation.')
        grant=match.get('udpGrant')
        native=dict(match,address='127.0.0.1',port=DIRECT_BRIDGE_POLICY['first_port'])
        target=super()._validated_target(native,name,spectator=spectator)
        if (not isinstance(grant,dict) or grant.get('matchId')!=target['matchId']
                or grant.get('port')!=match['port'] or not isinstance(grant.get('id'),str)):
            raise CommunityError('Match admission is unavailable. Wait for the host to start the match and try again.')
        key=(grant.get('matchId'),grant.get('id'))
        with self.lock:
            proxy=self.proxies.get(key)
            if proxy is not None and proxy.grant!=grant:raise CommunityError('UDP admission changed without a new identity.')
            if proxy is None:
                # One native session at a time is already enforced by CommunityGame.
                for old in self.proxies.values():old.close()
                self.proxies.clear()
                try:proxy=UdpClient(self.server_address,grant)
                except (TypeError,ValueError,OSError)as exc:raise CommunityError('UDP match admission could not be opened.')from exc
                self.proxies[key]=proxy
            return dict(target,endpoint='127.0.0.1:'+str(proxy.port))

    def close(self):
        with self.lock:
            for proxy in self.proxies.values():proxy.close()
            self.proxies.clear()

def main(root=ROOT):
    import tkinter as tk
    from tkinter import filedialog,messagebox
    from desktop_launcher import Desktop
    from community_game import CommunityGame
    from startup_paths import installation_options
    from client_support import discover_game
    from map_sync import MapSync
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
            messagebox.showerror('Direct host connection','Could not open the lobby. Ask the host to check the invitation, certificate and TCP forwarding. Use Change Host Invitation.bat to import a replacement.');return
    except Exception as exc:
        messagebox.showerror('Direct Starter setup',str(exc));return
    finally:chooser.destroy()
    class DirectDesktop(Desktop):
        def close(self):
            try:super().close()
            finally:lobby.close()
    window=tk.Tk();window.title('TRIBES 3 — Direct Host Starter')
    map_sync=MapSync(lobby,root,workspace)
    factory=lambda current:CommunityGame(current,root,source,workspace,workspace/'direct-desktop-control',map_sync=map_sync)
    gui=DirectDesktop(window,lobby,factory,steam_name_loader=lambda:read_steam_name(source,root/'base-game-manifest.json'),map_sync=map_sync)
    window.protocol('WM_DELETE_WINDOW',gui.close)
    try:window.mainloop()
    finally:lobby.close()

def change_invitation():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    try:
        filename=filedialog.askopenfilename(title='Choose the new player invitation',filetypes=[('Player invitation','*.json')])
        if filename:
            d=validate_connection(read_json(filename,16384));p=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'Tribes3DirectStarter/connection.json'
            write_json(p,d);messagebox.showinfo('Invitation saved','Close any other Direct Starter window, then reopen Direct Starter.')
    except Exception as exc:messagebox.showerror('Invitation',str(exc))
    finally:root.destroy()

if __name__=='__main__':main()
