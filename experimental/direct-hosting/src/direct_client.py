"""Separate direct-host Starter entry with local per-device credentials."""
import os, pathlib, secrets
from direct_network import (ENDPOINT_FIELDS, ENROLL_ROUTE, GROUP_FILE, MAX_DEVICES, TOKEN, UdpClient,
                            locked_state, read_json, validate_endpoint, validate_group, write_json)
from community_transport import CommunityClient,CommunityError
from dynamic_destination import DIRECT_BRIDGE_POLICY

ROOT=pathlib.Path(__file__).resolve().parent

def validate_connection(d,*,local_test=False):
    if not isinstance(d,dict)or set(d)!=ENDPOINT_FIELDS|{'format','access_token'}or d['format']!=1:
        raise ValueError('Choose an invitation exported by the direct host.')
    validate_endpoint(d,local_test=local_test)
    if not isinstance(d['access_token'],str)or not TOKEN.fullmatch(d['access_token']):
        raise ValueError('Invalid invitation credential.')
    return dict(d)

class DirectClient(CommunityClient):
    address_error = 'A direct host must have a public IPv4 address.'
    reconnect_requires_new_game = True

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

    def begin_game_attempt(self):
        """Use a new admission and native socket for each owned game process."""
        with self.lock:
            self.close()
            self.direct_session = secrets.token_hex(16)

    def enroll(self, group):
        response=self._request(ENROLL_ROUTE.removeprefix('/api/'),{
            'host_id':group['host_id'], 'enrollment_token':group['enrollment_token'],
            'device_token':self.access_token,
        },use_lobby_token=False)
        identity=response.get('device_id')
        if (set(response)!={'registered','device_id'} or response['registered'] is not True
                or type(identity) is not int or not 1<=identity<=MAX_DEVICES):
            raise CommunityError('The host returned an invalid registration receipt.')
        return identity

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

def group_connection(root, local, *, ssl_context=None, test_source=None):
    test=test_source is not None
    group=validate_group(read_json(root/GROUP_FILE,16384),local_test=test)
    path=local/'hosts'/(group['host_id']+'.json')
    with locked_state(path):
        if path.exists():
            state=read_json(path,16384)
        else:
            # Commit the token before the first network call so retries reuse it.
            state={'access_token':secrets.token_urlsafe(32),'device_id':None}
            write_json(path,state)
        if not isinstance(state,dict) or set(state)!={'access_token','device_id'}:
            raise ValueError('Invalid saved Direct Starter registration.')
        identity=state['device_id']
        if identity is not None and (type(identity) is not int or not 1<=identity<=MAX_DEVICES):
            raise ValueError('Invalid saved Direct Starter device ID.')
        connection=validate_connection(dict(validate_endpoint(group,local_test=test),format=1,
                                             access_token=state['access_token']),local_test=test)
        if identity is None:
            client=DirectClient(connection,ssl_context=ssl_context,test_source=test_source)
            state['device_id']=client.enroll(group)
            write_json(path,state)
        return connection

def main(root=ROOT, *, on_ready=None):
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
    lobby=None
    try:
        try:
            game,workspace=installation_options();source=discover_game(game)
        except RuntimeError as exc:
            # Steam discovery reports a missing or ambiguous game as RuntimeError.
            raise ValueError(str(exc)) from exc
        if (root/GROUP_FILE).exists():
            connection=group_connection(root,local)
        else:
            if not saved.exists():
                filename=filedialog.askopenfilename(title='Choose the player invitation JSON sent by your host',filetypes=[('Player invitation','*.json')])
                if filename:
                    write_json(saved,validate_connection(read_json(filename,16384)))
            connection=validate_connection(read_json(saved,16384)) if saved.exists() else None
        if connection is not None:
            lobby=DirectClient(connection)
            try:lobby.capabilities()
            except CommunityError:
                lobby.close()
                lobby=None
                messagebox.showerror('Direct host connection','Could not open the lobby. Ask the host to check your access, certificate and TCP forwarding.')
    except (OSError, ValueError, CommunityError) as exc:
        if lobby is not None:
            lobby.close()
        lobby=None
        messagebox.showerror('Direct Starter setup',str(exc))
    finally:chooser.destroy()
    if lobby is None:
        # A canceled invitation or unreachable host does not invalidate the update.
        if on_ready is not None:
            on_ready()
        return
    class DirectDesktop(Desktop):
        def close(self):
            try:super().close()
            finally:lobby.close()
    try:
        window=tk.Tk();window.title('TRIBES 3 — Direct Host Starter')
        map_sync=MapSync(lobby,root,workspace)
        factory=lambda current:CommunityGame(current,root,source,workspace,workspace/'direct-desktop-control',map_sync=map_sync)
        gui=DirectDesktop(window,lobby,factory,steam_name_loader=lambda:read_steam_name(source,root/'base-game-manifest.json'),map_sync=map_sync)
        window.protocol('WM_DELETE_WINDOW',gui.close)
        if on_ready is not None:
            window.update_idletasks()
            on_ready()
        window.mainloop()
    finally:
        lobby.close()

def change_invitation():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    try:
        if (ROOT/GROUP_FILE).exists():
            messagebox.showinfo('Group Starter','This Starter uses its bundled host. To switch hosts, open the Starter ZIP prepared by the other host.')
            return
        filename=filedialog.askopenfilename(title='Choose the new player invitation',filetypes=[('Player invitation','*.json')])
        if filename:
            d=validate_connection(read_json(filename,16384));p=pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'Tribes3DirectStarter/connection.json'
            write_json(p,d);messagebox.showinfo('Invitation saved','Close any other Direct Starter window, then reopen Direct Starter.')
    except Exception as exc:messagebox.showerror('Invitation',str(exc))
    finally:root.destroy()

if __name__=='__main__':main()
