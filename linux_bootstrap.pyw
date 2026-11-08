"""Windows Python entry inside Steam Proton; preserve the shared lobby and owned game pipeline."""
import argparse
import ctypes
import hashlib
import json
import os
import runpy
from pathlib import Path
import ssl
import sys
import traceback

ROOT = Path(__file__).resolve().parent


def check_proton():
    if sys.platform != 'win32':
        raise RuntimeError('The Proton bridge must run with the bundled Windows Python through Steam Proton.')
    wine = ctypes.WinDLL('ntdll').wine_get_version
    wine.restype = ctypes.c_char_p
    version = wine()
    if not version or os.environ.get('SteamAppId') != '2687970':
        raise RuntimeError('Open TRIBES 3 from Steam with the Linux launch option enabled.')
    return version.decode('ascii', errors='replace')


def check_owned_jobs(artifacts):
    sys.path.insert(0, str(ROOT/'lib'))
    from owned_native_session import run_owned_job
    marker = artifacts/'family-child-ready.txt'
    child = "import sys,time;from pathlib import Path;Path(sys.argv[1]).write_text('ready');time.sleep(30)"
    parent = ("import subprocess,sys,time;from pathlib import Path;"
              "subprocess.Popen([sys.executable,'-B','-c',"+repr(child)+",sys.argv[1]]);"
              "deadline=time.monotonic()+10\n"
              "while not Path(sys.argv[1]).is_file() and time.monotonic()<deadline: time.sleep(.05)\n"
              "sys.exit(0 if Path(sys.argv[1]).is_file() else 3)")
    result = run_owned_job([sys.executable, '-B', '-c', parent, str(marker)],
                           ROOT, dict(os.environ), artifacts/'job-check', budget=30)
    active = result.get('job_active_processes_after_cleanup', result.get('job_active_processes_at_parent_exit'))
    if (result.get('status') != 'terminal' or result.get('exit_code') != 0 or active != 0
            or result.get('job_total_processes', 0) < 2
            or result.get('job_active_processes_at_parent_exit', 0) < 1):
        raise RuntimeError('This Proton version did not pass the process ownership check. Try another Steam Proton version.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--launch-dir', type=Path, required=True)
    parser.add_argument('--ca-sha256', required=True)
    parser.add_argument('--probe-only', action='store_true')
    args = parser.parse_args()
    args.launch_dir.mkdir(parents=True, exist_ok=True)
    with (args.launch_dir/'bridge.log').open('x', encoding='utf-8', buffering=1) as log:
        old_streams = sys.stdout, sys.stderr
        try:
            sys.stdout = sys.stderr = log
            wine = check_proton()
            ca = args.launch_dir/'ca-bundle.pem'
            if not 0 < ca.stat().st_size <= 4*1024*1024 or hashlib.sha256(ca.read_bytes()).hexdigest() != args.ca_sha256:
                raise RuntimeError('The Linux certificate snapshot changed. Reopen Community Starter from Steam.')
            context = ssl.create_default_context(cafile=str(ca))
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            os.environ['SSL_CERT_FILE'] = str(ca)
            os.environ['TCL_LIBRARY'] = str(ROOT/'python/tcl/tcl8.6')
            os.environ['TK_LIBRARY'] = str(ROOT/'python/tcl/tk8.6')
            ownership = check_owned_jobs(args.launch_dir)
            import tkinter as tk
            probe = tk.Tk()
            probe.withdraw()
            probe.update_idletasks()
            probe.destroy()
            proof = {'wine_version': wine, 'tls_verification': True, 'tk_ready': True,
                     'job_exit_code': ownership['exit_code'], 'family_processes': ownership['job_total_processes'],
                     'descendants_cleaned_up': ownership.get('job_active_processes_after_cleanup') == 0,
                     'scope': 'Launcher preflight only; not game qualification'}
            (args.launch_dir/'bridge-ready.json').write_text(json.dumps(proof, indent=2)+'\n', encoding='utf-8')
            if args.probe_only:
                return 0
            startup = ROOT/'community_starter.pyw'
            sys.argv = [str(startup), '--game-dir', args.game_dir, '--workspace', args.workspace]
            launch = runpy.run_path(str(startup))['launch_startup']
            launch(ROOT, ssl_context=context)
            return 0
        except Exception as exc:
            traceback.print_exc()
            if not args.probe_only:
                ctypes.windll.user32.MessageBoxW(None, str(exc)+'\n\nDetails: '+str(args.launch_dir/'bridge.log'),
                                                'TRIBES 3 Community Starter', 0x10)
            return 1
        finally:
            sys.stdout, sys.stderr = old_streams


if __name__ == '__main__':
    raise SystemExit(main())
