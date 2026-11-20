"""Adapt only the Ubuntu preview's local package readers to its full inventory."""
from hashlib import sha256

MAX_PACKAGE_BYTES = 4 * 1024 * 1024
MAX_PACKAGE_FILES = 16384


def inventory_overlay(client):
    """Keep the released r59 readers and change their local bounds only."""
    readers = {
        'verified_file_cache.py': ('2 * 1024 * 1024', 'len(items) <= 10000', 3),
        'compare_map_packages.py': ('2*1024*1024', 'len(items)<=10000', 2),
        'lib/compare_map_packages.py': ('2*1024*1024', 'len(items)<=10000', 2),
    }
    overlay = {}
    for name, (limit, entries, occurrences) in readers.items():
        original = client.read(name)
        source = original.decode('utf-8')
        if source.count(limit) != occurrences or source.count(entries) != 1:
            raise ValueError(f'Review the changed Ubuntu package reader: {name}')
        patched = source.replace(limit, str(MAX_PACKAGE_BYTES)).replace(
            entries, entries.replace('10000',str(MAX_PACKAGE_FILES))).encode()
        overlay[name] = (sha256(original).hexdigest(), patched)
    return overlay
