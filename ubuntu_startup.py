"""Check the Linux Starter feed before importing the native launcher."""
from contextlib import contextmanager, ExitStack
import fcntl
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
UPDATE_STATE = '.linux-starter-update'


class StarterBusy(ValueError):
    pass


def private_area():
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')
    if not data.is_absolute():
        raise ValueError('XDG_DATA_HOME must be an absolute path.')
    directory = data/'ClanWarsUbuntuStarter'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError('Clan Wars Ubuntu Starter data must be private to your Linux user.')
    return directory


@contextmanager
def exclusive(path):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'rb') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StarterBusy('Clan Wars already has this session open.') from exc
        yield


def main():
    os.umask(0o077)
    sys.path[:0] = [str(ROOT), str(ROOT/'lib')]
    from starter_update import LINUX_CHANNEL, inside, launch_updated

    state = private_area()
    with exclusive(state/'starter.lock'), ExitStack() as steam:
        updates = inside(ROOT, UPDATE_STATE)

        def launch(on_ready=None):
            if on_ready is None:
                steam.close()

            def ready():
                on_ready()
                steam.close()

            from ubuntu_starter import main as launch_native
            return launch_native([], owned_state=state, on_ready=ready if on_ready else None)

        with (ROOT/'package-manifest.json').open('rb') as manifest:
            inventory = json.load(manifest)
        if inventory.get('linux_starter_update_channel') != LINUX_CHANNEL:
            return launch()
        try:
            steam.enter_context(exclusive(state/'steam-session.lock'))
        except StarterBusy:
            if (updates/'pending').exists():
                raise StarterBusy('Close TRIBES 3 so Clan Wars can finish recovering its last update.')
            return launch()
        try:
            updates.mkdir(exist_ok=True)
        except OSError as exc:
            print('Linux Starter update skipped:', exc, file=sys.stderr)
            return launch()
        return launch_updated(ROOT, updates, launch, channel=LINUX_CHANNEL)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Clan Wars Ubuntu Starter: {exc}', file=sys.stderr)
        sys.exit(1)
