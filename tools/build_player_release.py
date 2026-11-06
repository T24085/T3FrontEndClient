"""Rebuild a complete player ZIP from a pinned external package and source."""
import argparse,copy,datetime,hashlib,json,re,subprocess,sys,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_player_release import map_catalog,safe_name
SOURCE_MEMBERS={name:name for name in (
 'desktop_launcher.py','community_transport.py','community_game.py','client_preparation.py',
 'bulk_asset_cache.py','community_starter.pyw','map_catalog.py','compare_map_packages.py',
 'community_maps.py','steam_identity.py','player_names.py','runtime_health.py','startup_progress.py',
 'verified_file_cache.py','startup_timing.py','startup_paths.py','client_bootstrap.py',
 'bulk_verification_receipts.py','player_profile.py','lib/client_support.py',
 'lib/owned_native_session.py','lib/dynamic_destination.py',
 'lua/client.lua','lua/spectator_client.lua','lua/spectator_materials.lua')}
SOURCE_MEMBERS['client.py']='client_entry.py'

def encoded(value):return (json.dumps(value,indent=2)+'\n').encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()

def build(base,expected_sha,server_catalog,output,*,source=ROOT,frontend_ref,backend_ref,
          tag,release_id,archive_name,source_members=None,readme=None,known_issues=None):
 base,source,output=Path(base),Path(source).resolve(strict=True),Path(output).resolve()
 if source==output or source in output.parents:raise ValueError('Keep release artifacts outside the source checkout')
 if not all(re.fullmatch('[0-9a-f]{40}',ref)for ref in (frontend_ref,backend_ref)):raise ValueError('Full source commit references required')
 if Path(archive_name).name!=archive_name or not archive_name.endswith('.zip'):raise ValueError('Invalid archive filename')
 print('Checking the pinned base archive SHA256…',flush=True)
 with base.open('rb')as stream:
  if hashlib.file_digest(stream,'sha256').hexdigest()!=expected_sha:raise ValueError('Base archive SHA256 mismatch')
 server=json.loads(Path(server_catalog).read_bytes())
 with zipfile.ZipFile(base)as old:
  files=[i.filename for i in old.infolist()if not i.is_dir()]
  manifests=[n for n in files if n.endswith('/package-manifest.json')and n.count('/')==1]
  if len(manifests)!=1 or len(files)!=len(set(n.casefold()for n in files)):raise ValueError('Expected one inventoried complete base ZIP')
  prefix=manifests[0].split('/')[0]+'/'
  manifest_raw=old.read(manifests[0]);manifest=json.loads(manifest_raw);original_rows=manifest['files']
  for row in original_rows:safe_name(row['path'])
  if set(files)!={prefix+r['path']for r in original_rows}|set(manifests):raise ValueError('Base ZIP differs from its inventory')
  baseline_catalog=map_catalog(manifest)
  if baseline_catalog!=server['verified_map_catalog']:raise ValueError('Base map fingerprints differ from the verified server')
  replacements={};members=SOURCE_MEMBERS if source_members is None else source_members
  available={r['path']for r in original_rows};frozen_runtime={n for names in manifest['map_runtime'].values()for n in names}
  for destination,relative in members.items():
   safe_name(destination);safe_name(relative)
   if destination not in available:raise ValueError('Source member absent from base: '+destination)
   if destination in frozen_runtime or destination.startswith(('content/','runtime/','python/')):raise ValueError('Map/runtime payload is frozen: '+destination)
   path=source/relative
   if path.resolve(strict=True)!=path or source not in path.parents:raise ValueError('Source member escaped checkout')
   replacements[destination]=path.read_bytes()
  references={'frontend':frontend_ref,'backend':backend_ref}
  source_info={'format':1,'source_commits':references,'source_members':{n:{'source':members[n],'sha256':sha(raw)}for n,raw in replacements.items()},
               'base_archive_sha256':expected_sha,'frozen_inputs':'All cooked content, map fingerprint runtime, portable Python/Tk and native runtime binaries are retained from the pinned parent archive.',
               'backend_reference_scope':'Protocol/source reference only; this client build does not deploy or rebuild the server.'}
  created=datetime.datetime.now(datetime.timezone.utc).isoformat()
  info=json.loads(old.read(prefix+'RELEASE-INFO.json'))
  info.update(release=release_id,created_utc=created,source_commits=references,
              parent_release=info.get('release'),parent_build=manifest.get('build_id'),
              verified_map_catalog=baseline_catalog,spectator_perspective='first-person',client_only=True,
              known_issues=known_issues if known_issues is not None else
                           ['Armor/loadout menu defects and broader multiplayer qualification remain open.',
                            'Preparation may still take minutes on first verification and around 51 seconds on the measured USB-disk warm path.'])
  replacements['RELEASE-INFO.json']=encoded(info)
  replacements['SOURCE-INFO.json']=encoded(source_info)
  replacements['README-FIRST.txt']=('''TRIBES 3 COMMUNITY STARTER - COMPLETE WINDOWS CLIENT
November 5, 2026 - r6 community playtest

All authored maps and the portable launcher/runtime are included. No separate
map update is required. The 22 map choices include eight native CTF maps which
use your own matching Steam installation of TRIBES 3 Rivals.

TO PLAY
1. Start Steam with your own matching TRIBES 3 installation.
2. Connect to the community Tailscale network with an approved account.
3. Extract this entire ZIP into a fresh folder, outside an older client folder.
4. Run Start Community Starter.vbs (the BAT is an alternate launcher).
5. Create/join a lobby, choose teams and a map, then start and join the match.
   Keep Starter open while playing. Its close action also stops its owned game.
   Spectators use Live matches; F5/F6 switch players and F7 resets first person.
   Third-person spectator viewing is unavailable in this release.

R6 UPDATES
Map choices wait for server confirmation and recover from lost replies. Existing
lobby membership can resume after a crash. Automatic refreshes no longer flash
the action buttons. File preparation uses four workers and shows a file counter.

FIRST LAUNCH AND LIMITS
The first verification/cache fill can take several minutes. Warm preparation
was measured at about 51 seconds on USB disks; 6-10 seconds is not guaranteed.
Staging may need a large verified cache plus a 2 GiB free-space reserve.
Existing installation preferences are retained; no personal staging path or
player profile is included. Downloading does not grant private network access.

The reported armor/loadout menu defects and broader multiplayer qualification
remain open. This is a community playtest, not an official TRIBES 3 release.
Original game files, server operator tools, credentials and private keys are
not included. SOURCE-INFO.json records source and frozen-package provenance.
''').replace('\n','\r\n').encode()
  if readme is not None:
   raw=Path(readme).read_bytes()
   if not raw or len(raw)>32768:raise ValueError('A bounded release README is required')
   replacements['README-FIRST.txt']=raw
  manifest=copy.deepcopy(manifest)
  manifest.update(build_id='Tribes3-Community-'+release_id,release_id=release_id,
                  revision_id=release_id,source_commits=references,
                  lobby_recovery_revision='lobby-recovery-20261105-r3',spectator_perspective='first-person')
  rows=[]
  for row in original_rows:
   name=row['path'];raw=replacements.get(name)
   rows.append(dict(row)if raw is None else {'path':name,'bytes':len(raw),'sha256':sha(raw)})
  for name,raw in replacements.items():
   if name not in available:rows.append({'path':name,'bytes':len(raw),'sha256':sha(raw)})
  manifest['files']=sorted(rows,key=lambda r:r['path'])
  if map_catalog(manifest)!=baseline_catalog:raise ValueError('Source overlay changed map fingerprints')
  output.mkdir(parents=True,exist_ok=False);archive=output/archive_name;top='TRIBES3-Community-Starter/'
  with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True)as new:
   for index,row in enumerate(original_rows,1):
    name=row['path'];digest=hashlib.sha256();count=0
    if name in replacements:
     with old.open(prefix+name)as incoming:
      while chunk:=incoming.read(4*1024*1024):digest.update(chunk);count+=len(chunk)
     new.writestr(top+name,replacements[name])
    else:
     info=zipfile.ZipInfo(top+name,old.getinfo(prefix+name).date_time)
     info.compress_type=zipfile.ZIP_DEFLATED
     with old.open(prefix+name)as incoming,new.open(info,'w',force_zip64=True)as outgoing:
      while chunk:=incoming.read(4*1024*1024):digest.update(chunk);count+=len(chunk);outgoing.write(chunk)
    if digest.hexdigest()!=row['sha256']or count!=row['bytes']:raise ValueError('Base inventory mismatch: '+name)
    if index%1000==0:print(f'Built and checked {index}/{len(original_rows)} base members',flush=True)
   for name,raw in replacements.items():
    if name not in available:new.writestr(top+name,raw)
   new.writestr(top+'package-manifest.json',encoded(manifest))
 if archive.stat().st_size>=2*1024**3:raise ValueError('Complete archive exceeds the release asset limit')
 proof={'tag':tag,'archive':archive.name,'release':release_id,'source_commits':references,
        'base_archive_sha256':expected_sha,'base_package_manifest_sha256':sha(manifest_raw),
        'source_members':source_info['source_members'],'verified_base_members':len(original_rows),
        'map_payloads_preserved':True,'map_count':len(baseline_catalog),'created_utc':created}
 (output/'BUILD-PROVENANCE.json').write_bytes(encoded(proof))
 print('Complete archive built:',archive,flush=True)
 return archive

def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),'-c','safe.directory='+Path(repo).resolve().as_posix(),*args],text=True).strip()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('base','server-catalog','output','backend-repo'):p.add_argument('--'+name,type=Path,required=True)
 for name in ('base-sha256','tag','release-id','archive-name'):p.add_argument('--'+name,required=True)
 p.add_argument('--readme',type=Path);p.add_argument('--known-issues',type=Path)
 a=p.parse_args();refs={repo:git(repo,'rev-parse','HEAD')for repo in (ROOT,a.backend_repo)}
 if any(git(repo,'status','--porcelain')for repo in refs):raise RuntimeError('Commit the selected source before building')
 build(a.base,a.base_sha256,a.server_catalog,a.output,frontend_ref=refs[ROOT],backend_ref=refs[a.backend_repo],
       tag=a.tag,release_id=a.release_id,archive_name=a.archive_name,readme=a.readme,
       known_issues=json.loads(a.known_issues.read_bytes())if a.known_issues else None)
 if any(git(repo,'rev-parse','HEAD')!=ref or git(repo,'status','--porcelain')for repo,ref in refs.items()):raise RuntimeError('Source changed while building; do not publish this archive')
if __name__=='__main__':main()
