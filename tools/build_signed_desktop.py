"""Build the signed Starter desktop and artwork payloads."""
import argparse
import base64
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ART = ('phoenix-world.png', 'phoenix-icon.png', 'phoenix-emblem.png', 'phoenix.ico',
               'blood-eagle-world.png', 'blood-eagle-emblem.png',
               'diamond-sword-world.png', 'diamond-sword-emblem.png')
PROFILE_ART = ('blood-eagle-2-world.png', 'blood-eagle-2-emblem.png')
ART = DESKTOP_ART + PROFILE_ART


def build_payload(module, art_key, names):
    source = (ROOT / module).read_bytes()
    marker = art_key + b' = {}'
    if source.count(marker) != 1:
        raise ValueError(f'Expected one artwork insertion point in {module}.')
    assets = {name: base64.b85encode((ROOT / 'branding' / name).read_bytes()) for name in names}
    candidate = source.replace(marker, art_key + b' = ' + repr(assets).encode('ascii'))
    # Keep this module usable as a script and from the release builder.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from starter_update import MAX_FILE

    if len(candidate) > MAX_FILE:
        raise ValueError(f'{module} exceeds the signed update file limit.')
    compile(candidate, module, 'exec')
    return candidate


def build():
    return build_payload('desktop_launcher.py', b'PHOENIX_ART', DESKTOP_ART)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='Desktop module output (artwork module goes beside it)')
    args = parser.parse_args()
    profile_output = args.output.with_name('player_profile.py')
    if (args.output.resolve() in (ROOT / 'desktop_launcher.py', ROOT / 'player_profile.py')
            or profile_output.resolve() == ROOT / 'player_profile.py'
            or args.output.resolve() == profile_output.resolve()):
        parser.error('Choose a distinct desktop output in a staging directory.')
    desktop_payload = build()
    profile_payload = build_payload('player_profile.py', b'STARTER_SKIN_ART', PROFILE_ART)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(desktop_payload)
    profile_output.write_bytes(profile_payload)
