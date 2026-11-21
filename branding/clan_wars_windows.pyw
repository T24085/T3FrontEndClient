import ctypes
import os
from pathlib import Path
import sys
import traceback

from starter_update import DIRECT_CHANNEL, run_startup


root = Path(__file__).resolve().parent
os.environ['TCL_LIBRARY'] = str(root/'python/tcl/tcl8.6')
os.environ['TK_LIBRARY'] = str(root/'python/tcl/tk8.6')
log = Path(os.environ.get('LOCALAPPDATA') or Path.home())/'Tribes3DirectStarter/launcher.log'
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TribesRivals.ClanWars.CommunityMod')
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8', buffering=1) as stream:
        sys.stdout = sys.stderr = stream
        try:
            def launch(on_ready):
                from clan_wars import launch as start
                start(root, on_ready=on_ready)
            run_startup(root, launch, channel=DIRECT_CHANNEL)
        except Exception:
            traceback.print_exc()
            raise
except Exception as exc:
    ctypes.windll.user32.MessageBoxW(None, str(exc)+'\n\nLog: '+str(log),
                                   'Tribes 3 Mod Community Edition: Phoenix Rising', 0x10)
