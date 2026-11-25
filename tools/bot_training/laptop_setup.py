"""Configure a relocated local training bundle and start its private dashboard."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from itertools import batched
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import BadZipFile, ZipFile

from train import publish


def rebase_traces(value, root):
    if isinstance(value, dict):
        changed = False
        for key, item in value.items():
            if key == 'trace' and isinstance(item, str):
                trace = Path(item)
                relative = Path(*trace.parts[-3:]) if trace.is_absolute() else trace
                if not relative.parts or relative.parts[0] != 'Sessions':
                    continue
                if len(relative.parts) != 3 or '..' in relative.parts:
                    raise ValueError('Invalid trace path in training snapshot.')
                target = str(root/relative)
                if item != target:
                    value[key] = target
                    changed = True
            elif rebase_traces(item, root):
                changed = True
        return changed
    if isinstance(value, list):
        return sum(rebase_traces(item, root) for item in value) > 0
    return False


def restore_history(root):
    archive = root/'TrainingHistory.zip'
    sessions = root/'Sessions'
    restored = sessions/'.history-restored'
    if not archive.is_file() or restored.is_file():
        return
    print('Restoring the copied match and replay history...', flush=True)
    with ZipFile(archive) as history, ThreadPoolExecutor(max_workers=8) as workers:
        items = history.infolist()
        if (len({item.filename.casefold() for item in items}) != len(items)
                or any(not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_-]+\.csv', item.filename) for item in items)):
            raise ValueError('Invalid file in the copied training history.')

        def restore(item):
            target = sessions/item.filename
            if target.is_file() and target.stat().st_size == item.file_size:
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.training-tmp')
            temporary.write_bytes(history.read(item))
            temporary.replace(target)

        for group in batched(items, 128):
            for _ in workers.map(restore, group):
                pass
    publish(restored, 'Restored\n')


def configure(root):
    game_cache = root/'GameCache'
    if not (game_cache/'game/Topaz/Binaries/Win64/TribesRivals.exe').is_file():
        raise ValueError('The training folder is missing its GameCache. Copy the whole folder to this computer.')
    paths = dict(workspace='workspace', host_fixture='runtime/fixture', host_argv='runtime/host-argv.json',
                 host_package='runtime/host', client_package='runtime/client', cached_client_session='GameCache',
                 runs='Sessions')
    for key, value in (('map_catalog','runtime/training-catalog.json'), ('season_runtime','runtime/season')):
        if (root/value).exists():
            paths[key] = value
    for key, value in paths.items():
        if not (root/value).exists():
            raise ValueError(f'Training bundle is missing {key}.')
    config = {key: str(root/value) for key, value in paths.items()}
    publish(root/'practice.json', json.dumps(config, indent=2)+'\n')
    for path in root.glob('DashboardRuns/*/practice.json'):
        previous = json.loads(path.read_bytes())
        updated = previous | config
        if previous != updated:
            publish(path, json.dumps(updated, indent=2)+'\n')
    for pattern in ('Campaign-*/**/progress.json', 'DashboardRuns/*/progress.json'):
        for path in root.glob(pattern):
            data = json.loads(path.read_bytes())
            if rebase_traces(data, root):
                publish(path, json.dumps(data, indent=2)+'\n')


def tailscale_settings(port):
    tailscale = shutil.which('tailscale') or str(Path(os.environ['ProgramFiles'])/'Tailscale/tailscale.exe')
    status = json.loads(subprocess.check_output([tailscale, 'status', '--json']))
    if status.get('BackendState') != 'Running':
        raise ValueError('Sign in to Tailscale on this laptop, then open the launcher again.')
    device = status['Self']
    owner = status['User'][str(device['UserID'])]['LoginName']
    hostname = device['DNSName'].rstrip('.')
    origin = f'https://{hostname}:8444'
    target = f'http://127.0.0.1:{port}'
    serve = json.loads(subprocess.check_output([tailscale, 'serve', 'status', '--json']) or '{}')
    site = f'{hostname}:8444'
    prior = serve.get('Web', {}).get(site, {}).get('Handlers', {}).get('/', {})
    if prior and prior.get('Proxy') != target:
        raise ValueError('The laptop already has another service on Tailscale port 8444.')
    if serve.get('AllowFunnel', {}).get(site):
        raise ValueError('Training controls require a tailnet-only Tailscale Serve address.')
    if not prior:
        subprocess.run([tailscale, 'serve', '--bg', '--https=8444', '--yes', target], check=True)
    return dict(owner=owner, tailnet_origin=origin)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18870)
    parser.add_argument('--tailscale', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    configure(root)
    access = dict(local_control=True, origin=f'http://127.0.0.1:{args.port}')
    if args.tailscale:
        access.update(tailscale_settings(args.port))
    runner = root/'tools/bot_training/dashboard_run.py'
    settings = root/'dashboard-training-settings.json'
    publish(settings, json.dumps(dict(access, runner=str(runner)))+'\n')
    print(f'Training dashboard: {access["origin"]}/?view=1&tab=dashboard', flush=True)
    if args.tailscale:
        print(f'Tailscale dashboard: {access["tailnet_origin"]}/?view=1&tab=dashboard', flush=True)
    command = [sys.executable, '-B', str(runner.parent/'dashboard/serve_dashboard.py'),
               '--root', str(root), '--index', str(root/'Dashboard/index.html'),
               '--training-settings', str(settings), '--port', str(args.port)]
    with subprocess.Popen(command) as dashboard:
        try:
            restore_history(root)
        except (OSError, ValueError, BadZipFile) as error:
            print(f'The copied replays could not be restored. {error}', file=sys.stderr)
        status = dashboard.wait()
        if status:
            raise subprocess.CalledProcessError(status, command)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, BadZipFile, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
