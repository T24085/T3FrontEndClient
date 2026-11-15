"""Inspect or reclaim historical Starter game payloads with terminal Job evidence."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client_preparation import MAX_AGE_SECONDS, empty_client_job, logged_stage, remove_staged_game, staged_session


def regular_text(path, maximum):
    if path.is_symlink() or path.is_junction() or path.resolve(strict=True) != path:
        raise ValueError('Unexpected cleanup evidence location.')
    with path.open('rb') as stream:
        payload = stream.read(maximum + 1)
    if len(payload) > maximum:
        raise ValueError('Unexpected cleanup evidence size.')
    return payload.decode('utf-8')


def historical_payloads(workspace, package):
    """Select only expired sessions announced by this installation's owned jobs."""
    control_names = ('direct-desktop-control', 'desktop-control')
    receipts = {}
    for name in control_names:
        control = workspace / name
        if not control.is_dir() or control.resolve() != control or control.is_junction():
            continue
        for attempt in control.iterdir():
            if not re.fullmatch(r'(?:prepare-)?[0-9a-f]{32}', attempt.name) or attempt.is_junction():
                continue
            owner = attempt / 'owner'
            try:
                record = json.loads(regular_text(owner/'execution.json', 65536))
                command = record['argv']
                if (not isinstance(command, list) or len(command) < 4
                        or Path(record['cwd']) != package
                        or Path(command[0]) != package/'python/python.exe'
                        or Path(command[3]) != package/'client.py'
                        or '--workspace' not in command
                        or Path(command[command.index('--workspace') + 1]) != workspace):
                    continue
                run = logged_stage(regular_text(owner/'stdout.log', 1048576).splitlines())
                if run is None and '--prepared' in command:
                    path = Path(command[command.index('--prepared') + 1])
                    if path.name == 'prepared.json':
                        run = path.parent
                if run is not None:
                    run = staged_session(workspace, run)
                    receipts.setdefault(run, []).append(
                        record.get('status') in {'terminal', 'cancelled_by_owner_request', 'deadline_terminated',
                                                 'supervisor_error'}
                        and record.get('assigned_suspended') is True and empty_client_job(record))
            except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                continue

    expiry = time.time() - MAX_AGE_SECONDS
    eligible = []
    kept = []
    for run in sorted(workspace.iterdir()):
        if not re.fullmatch(r'client-[0-9a-f]{12}', run.name):
            continue
        try:
            staged_session(workspace, run)
            game = run/'game'
            if game.is_symlink() or game.is_junction():
                raise ValueError('Staged payload is a link.')
            if not game.is_dir():
                continue
            if (run.stat().st_mtime <= expiry and receipts.get(run) and all(receipts[run])):
                eligible.append(run)
            else:
                kept.append(run)
        except (OSError, ValueError):
            kept.append(run)
    return eligible, kept


def require_closed(workspace, package):
    """Reject same-workspace games and installed launchers before offline cleanup."""
    if os.name != 'nt':
        raise ValueError('Use this historical cleanup command on Windows.')
    command = r"""
$rows = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    $_.Name -match '^(pythonw?|TribesRivals|Tribes3.*Starter)\.exe$'
} | Select-Object ProcessId,Name,ExecutablePath,CommandLine)
ConvertTo-Json -InputObject $rows -Compress
"""
    output = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                     encoding='utf-8', errors='replace', timeout=30)
    markers = tuple(str(path).replace('/', '\\').casefold() for path in (workspace, package))
    for row in json.loads(output):
        if row['ProcessId'] == os.getpid():
            continue
        observed = ' '.join((row['ExecutablePath'] or '', row['CommandLine'] or '')).replace('/', '\\').casefold()
        if any(marker in observed for marker in markers) or not observed.strip():
            raise ValueError('Close Starter and its local game before applying cleanup.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Remove eligible game payloads with Starter closed')
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    package = args.package.resolve(strict=True)
    if workspace == package or package in workspace.parents or workspace in package.parents:
        parser.error('Select separate installed package and workspace directories.')
    if not (package/'package-manifest.json').is_file():
        parser.error('Select the installed Starter package.')
    if args.apply:
        require_closed(workspace, package)
    eligible, kept = historical_payloads(workspace, package)
    failures = []
    removed = 0
    if args.apply:
        for run in eligible:
            try:
                remove_staged_game(workspace, run)
                removed += 1
            except (OSError, ValueError) as exc:
                failures.append({'session': run.name, 'error': str(exc)})
    print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', 'eligible': len(eligible),
                      'retained': len(kept), 'removed': removed, 'failures': failures}, indent=2))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
