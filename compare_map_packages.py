"""Verify and compare cooked community maps in two local development bundles.

This read-only comparison does not prove game-protocol compatibility or verify
the installed base game. It is not yet a client/server version handshake.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from community_maps import LEGACY_MAPS, declared_definitions, declared_maps, declared_shared_content
from verified_file_cache import digest as verified_digest


MAPS=LEGACY_MAPS


class CompatibilityError(ValueError): pass


def read_package_manifest(bundle):
    root=Path(bundle).resolve(strict=True)
    with (root/'package-manifest.json').open('rb') as stream: raw=stream.read(2*1024*1024+1)
    if len(raw)>2*1024*1024: raise CompatibilityError('Manifest is too large.')
    manifest=json.loads(raw)
    if not isinstance(manifest,dict): raise CompatibilityError('Invalid package manifest.')
    return root,manifest


def packaged_map_ids(bundle):
    _,manifest=read_package_manifest(bundle)
    try: return declared_maps(manifest)
    except ValueError as exc: raise CompatibilityError(str(exc)) from exc


def inventory(bundle, *, manifest_reader=read_package_manifest):
    root,manifest=manifest_reader(bundle)
    items=manifest.get('files')
    if not isinstance(items,list) or not 1<=len(items)<=10000: raise CompatibilityError('Invalid manifest inventory.')
    try:
        definitions=declared_definitions(manifest)
        maps=tuple(definitions)
        shared_content=declared_shared_content(manifest,definitions)
    except ValueError as exc: raise CompatibilityError(str(exc)) from exc
    runtime=manifest.get('map_runtime')
    if runtime is None:
        runtime={name:[] for name in maps}
    elif not isinstance(runtime,dict) or set(runtime)!=set(maps):
        raise CompatibilityError('Runtime map ownership differs from declared maps.')
    for paths in runtime.values():
        if (not isinstance(paths,list) or any(not isinstance(path,str) for path in paths)
                or len(set(paths))!=len(paths)):
            raise CompatibilityError('Invalid runtime map inventory.')
        for path in paths:
            rel=PurePosixPath(path)
            if (rel.as_posix()!=path or not path.startswith('lua/') or not path.endswith('.lua')
                    or rel.is_absolute() or '..' in rel.parts or ':' in path or '\\' in path):
                raise CompatibilityError('Unsafe runtime map path.')
    groups={name:{} for name in maps};base=None;seen=set();listed=set();expected_content=set()
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('path'),str): raise CompatibilityError('Invalid inventory entry.')
        path=item['path'];rel=PurePosixPath(path)
        normalized=rel.as_posix().casefold()
        if ('\\' in path or rel.is_absolute() or '..' in rel.parts or ':' in path or not rel.parts or normalized in seen):
            raise CompatibilityError('Unsafe or duplicate inventory path.')
        seen.add(normalized)
        listed.add(path)
        owners=[]
        for name in maps:
            definition=definitions[name]
            # Clear/weather levels share one asset family, but retain distinct
            # level identities and include only their own level package files.
            level='content/Maps/Community/'+definition.asset_group+'/'+definition.level+'.'
            assets='content/Community/'+definition.asset_group+'/'
            shared='content/Community/'+definition.shared_group+'/' if definition.shared_group else None
            if path.startswith((level,assets)) or (shared and path.startswith(shared)) or path in runtime[name]:
                owners.append(name)
        for prefix,names in shared_content.items():
            if path.startswith(prefix):owners.extend(name for name in names if name not in owners)
        if path.startswith('content/'):
            if not owners: raise CompatibilityError('Unrecognized staged content: '+path)
            expected_content.add(normalized)
        if not owners and path!='base-game-manifest.json': continue
        length,digest=item.get('bytes'),item.get('sha256')
        if type(length) is not int or length<0 or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise CompatibilityError('Invalid content digest.')
        target=root.joinpath(*rel.parts).resolve(strict=True)
        if root not in target.parents or not target.is_file() or target.stat().st_size!=length:
            raise CompatibilityError('Missing, escaped, or changed content: '+path)
        actual=verified_digest(target)
        if actual!=digest: raise CompatibilityError('Content digest mismatch: '+path)
        if not owners: base=digest
        else:
            for owner in owners: groups[owner][path]=(length,digest)
    if any(path not in listed for paths in runtime.values() for path in paths):
        raise CompatibilityError('Declared map runtime is missing from the package inventory.')
    content=root/'content'
    if not content.is_dir() or content.is_symlink() or content.is_junction():
        raise CompatibilityError('Content root is missing or is a link.')
    actual_content=set()
    def walk_error(error): raise CompatibilityError('Content directory could not be inspected.') from error
    for directory, directories, files in os.walk(content,followlinks=False,onerror=walk_error):
        for name in directories+files:
            target=Path(directory)/name
            if target.is_symlink() or target.is_junction():
                raise CompatibilityError('Linked content is not supported: '+str(target.relative_to(root)))
        for name in files:
            target=Path(directory)/name
            if not target.is_file(): raise CompatibilityError('Unsupported content entry.')
            relative=target.relative_to(root).as_posix().casefold()
            if relative in actual_content: raise CompatibilityError('Duplicate staged content path.')
            actual_content.add(relative)
    if actual_content != expected_content:
        raise CompatibilityError('Staged content differs from the package inventory.')
    if base is None: raise CompatibilityError('Base-game manifest is missing.')
    for name in maps:
        paths=groups[name]
        definition=definitions[name]
        if definition.native:
            if not runtime[name]: raise CompatibilityError('Native map runtime is missing: '+name)
            continue
        prefix='content/Maps/Community/'+definition.asset_group+'/'+definition.level
        for required in (prefix+'.umap',prefix+'.uexp'):
            if required not in paths: raise CompatibilityError('Map inventory is incomplete: '+name)
        if not any(path.startswith('content/Community/'+definition.asset_group+'/') for path in paths):
            raise CompatibilityError('Map assets are missing: '+name)
    return base,groups


def compare(host,client):
    host_base,host_groups=inventory(host);client_base,client_groups=inventory(client)
    result={'base_game_manifest_matches':host_base==client_base,'map_identities_match':host_groups.keys()==client_groups.keys(),'maps':{}}
    for name in sorted(host_groups.keys()|client_groups.keys()):
        server,player=host_groups.get(name,{}),client_groups.get(name,{})
        common=server.keys() & player.keys()
        result['maps'][name]={'matches':server==player,'host_files':len(server),'client_files':len(player),
                              'missing_on_client':len(server.keys()-player.keys()),
                              'extra_on_client':len(player.keys()-server.keys()),
                              'changed':sum(server[k]!=player[k] for k in common)}
    result['compatible_map_files']=result['base_game_manifest_matches'] and result['map_identities_match'] and all(x['matches'] for x in result['maps'].values())
    result['scope']='verified cooked maps, declared shared map runtime and base-game manifest; no gameplay or protocol compatibility proof'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private_host');parser.add_argument('client')
    args=parser.parse_args()
    try: result=compare(args.private_host,args.client)
    except (OSError,ValueError,TypeError) as exc:
        print(json.dumps({'compatible_map_files':False,'error':str(exc)},indent=2));return 1
    print(json.dumps(result,indent=2))
    return 0 if result['compatible_map_files'] else 1


if __name__=='__main__': raise SystemExit(main())
