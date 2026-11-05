"""Windowless GUI entry. Keep failures inspectable when stdout is unavailable."""
import ctypes
import datetime
import os
from pathlib import Path
import sys
import traceback
import uuid


def show_error(message):
    ctypes.windll.user32.MessageBoxW(None, message, 'TRIBES 3 Community Starter', 0x10)


def main():
    root = Path(__file__).resolve().parent
    os.environ['TCL_LIBRARY'] = str(root / 'python/tcl/tcl8.6')
    os.environ['TK_LIBRARY'] = str(root / 'python/tcl/tk8.6')
    directory = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Tribes3CommunityStarter/logs'
    log = directory / ('launcher-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.log')
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stream = log.open('x', encoding='utf-8', buffering=1)
    except OSError as exc:
        show_error('The launcher could not create its log file: ' + str(exc))
        return 1
    previous = sys.stdout, sys.stderr
    try:
        with stream:
            sys.stdout = sys.stderr = stream
            try:
                from desktop_launcher import main as launch
                launch()
            except BaseException as exc:
                if isinstance(exc, SystemExit) and exc.code in (None, 0):
                    return 0
                traceback.print_exc()
                show_error('Community Starter could not start.\n\n' + str(exc) + '\n\nDetails were saved to:\n' + str(log))
                return 1
    finally:
        sys.stdout, sys.stderr = previous
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
