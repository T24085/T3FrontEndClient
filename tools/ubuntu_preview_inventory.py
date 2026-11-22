"""Adapt the released Ubuntu preview readers to its full local inventory."""
from hashlib import sha256
import re

MAX_PACKAGE_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_FILES = 16384
MAX_PREPARED_FILES = MAX_PACKAGE_FILES + 1


def proton_profile_overlay(released, source):
    """Keep the signed profile implementation around the Wine-aware folder lookup."""
    lookup = re.compile(rb'(?ms)^def user_profile_root\(\):\n.*?(?=^def _identity\(path\):)')
    old, = lookup.findall(released)
    updated, = lookup.findall(source)
    if old != updated and sha256(old).hexdigest() != '8761965494c97c2576dc212b9661341512a7a14807b2c8c94353a0187f80bc34':
        raise ValueError('Review the changed player profile folder lookup before overlaying it.')
    result = released.replace(old, updated, 1)
    compile(result, 'player_profile.py', 'exec')
    return result


def inventory_overlay(client, *, signed_inventory=False):
    """Patch the exact packaged modules while keeping other client editions intact."""
    compare = (
        ('2*1024*1024', str(MAX_PACKAGE_BYTES), 2),
        ('len(items)<=10000', f'len(items)<={MAX_PACKAGE_FILES}', 1),
    )
    readers = {
        'verified_file_cache.py': (
            ('2 * 1024 * 1024', str(MAX_PACKAGE_BYTES), 3),
            ('len(items) <= 10000', f'len(items) <= {MAX_PACKAGE_FILES}', 1),
        ),
        'compare_map_packages.py': compare,
        'lib/compare_map_packages.py': compare,
        'client_preparation.py': (
            ('MAX_DESCRIPTOR_BYTES=4*1024*1024',
             f'MAX_DESCRIPTOR_BYTES=8*1024*1024\nMAX_PREPARED_FILES={MAX_PREPARED_FILES}', 1),
            ('<=10000', '<=MAX_PREPARED_FILES', 2),
            ('json.dumps(record,indent=2)', "json.dumps(record,separators=(',',':'))", 1),
        ),
        'community_game.py': (
            ('from client_preparation import empty_client_job',
             'from client_preparation import MAX_DESCRIPTOR_BYTES, MAX_PREPARED_FILES, empty_client_job', 1),
            ('path.stat().st_size>4*1024*1024', 'path.stat().st_size>MAX_DESCRIPTOR_BYTES', 1),
            ('done<=total<=10000', 'done<=total<=MAX_PREPARED_FILES', 1),
        ),
    }
    if signed_inventory:
        # The Direct feed supplies its own verified cache and preparation readers.
        readers = {name: readers[name] for name in ('compare_map_packages.py', 'lib/compare_map_packages.py')}
    overlay = {}
    for name, replacements in readers.items():
        original = client.read(name)
        source = original.decode('utf-8')
        for before, after, occurrences in replacements:
            if source.count(before) != occurrences:
                raise ValueError(f'Review the changed Ubuntu package reader: {name}')
            source = source.replace(before, after)
        patched = source.encode()
        compile(patched, name, 'exec')
        overlay[name] = (sha256(original).hexdigest(), patched)
    return overlay
