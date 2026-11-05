"""Version fingerprints for locally verified community map inventories."""
import hashlib
import json

from compare_map_packages import inventory


def verified_catalog(bundle):
    """Verify listed files, then fingerprint each map and base manifest.

    A digest detects differing packaged content; it does not authenticate the
    client, prove gameplay compatibility, or verify the installed base game.
    """
    base, groups=inventory(bundle)
    result={}
    for name in groups:
        entries=[[path,size,digest] for path,(size,digest) in sorted(groups[name].items())]
        data=json.dumps({'format':1,'map':name,'base_manifest_sha256':base,'files':entries},
                        sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
        result[name]=hashlib.sha256(data).hexdigest()
    return result
