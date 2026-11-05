"""Create small updater ZIPs from the paired source checkouts; maps stay intact."""
import argparse,hashlib,json,zipfile
from pathlib import Path
def build(client,server,output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True);proof={}
 for kind,repo,files in [('Client',Path(client),['desktop_launcher.py','community_game.py','community_transport.py']),('Server',Path(server),['lobby_controller.py','lobby_http.py','community_transport.py'])]:
  target=output/('TRIBES3-Lobby-Recovery-'+kind+'-20261105-r1.zip')
  if target.exists():raise ValueError('Fresh output required: '+str(target))
  prefix='operator/'if kind=='Server'else'';members={'apply_lobby_recovery_update.py':(repo/'tools/apply_lobby_recovery_update.py').read_bytes()}
  members.update({'lobby-recovery-payload/'+prefix+n:(repo/n).read_bytes()for n in files})
  python='host\\python\\python.exe'if kind=='Server'else'python\\python.exe'
  launcher='@echo off\r\n"%~dp0'+python+'" -B "%~dp0apply_lobby_recovery_update.py" --kind '+kind.lower()+' --root "%~dp0." --payload "%~dp0lobby-recovery-payload"\r\nif errorlevel 1 (echo Update failed. Existing package or backup files were retained.)\r\npause\r\n'
  members['Apply '+kind+' Lobby Fix.bat']=launcher.encode()
  text='Lobby map-selection/session-recovery update, 2026-11-05 r1.\n\nExtract these files directly into your existing '+kind.lower()+' package folder (the folder containing '+('host and operator'if kind=='Server'else'python and Start Community Starter.vbs')+'). Then run Apply '+kind+' Lobby Fix.bat.\n\n'
  if kind=='Server':text+='The updater stops/restarts an idle lobby cooperatively. If an active match is present it refuses to interrupt it; stop that match/server in the operator first, then update and start the server again. No SSH, firewall or account settings are changed.\n'
  else:text+='Close Community Starter before applying; open it again afterward. Only three Python modules and their package inventory change. Existing maps, profiles and connection settings are preserved.\n'
  text+='\nBoth client and server need this update for automatic lobby recovery. The client map-selection queue and join-time map check also work with the previous server. This does not include the separate native armor/weapon fix.\n'
  members['README-LOBBY-FIX.txt']=text.encode()
  with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED)as z:
   for n,b in members.items():z.writestr(n,b)
  with zipfile.ZipFile(target)as z:assert z.testzip()is None
  proof[kind.lower()]={'archive':str(target),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
 (output/'UPDATE-PACKAGES.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--client',type=Path,required=True);p.add_argument('--server',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.client,a.server,a.output)
