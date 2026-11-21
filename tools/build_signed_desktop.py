"""Build the self-contained desktop module for existing signed Starter installations."""
import argparse
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ART = ('phoenix-world.png', 'phoenix-icon.png', 'phoenix-emblem.png', 'phoenix.ico')


def build():
    source = (ROOT / 'desktop_launcher.py').read_bytes()
    marker = b'PHOENIX_ART = {}'
    if source.count(marker) != 1:
        raise ValueError('Expected one artwork insertion point in desktop_launcher.py.')
    assets = {name: base64.b85encode((ROOT / 'branding' / name).read_bytes()) for name in ART}
    candidate = source.replace(marker, b'PHOENIX_ART = ' + repr(assets).encode('ascii'))
    compile(candidate, 'desktop_launcher.py', 'exec')
    return candidate


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.resolve() == ROOT / 'desktop_launcher.py':
        parser.error('Choose a staging path outside the desktop source.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(build())
