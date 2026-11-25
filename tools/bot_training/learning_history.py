"""Find compatible checkpoints from previous dashboard batches."""
import hashlib
import json
from pathlib import Path
import re


MOVEMENT = 'fly-through-v1'
RUN_ID = re.compile(r'run\d{14}[a-f0-9]{8}')
SHA256 = re.compile(r'[0-9a-f]{64}')


def request_provenance(config, map_id, mode, *, paired_ctf_rules=False):
    catalog = config.get('map_catalog')
    inventory = json.loads(Path(catalog).read_bytes()) if catalog else {}
    revision = inventory.get('revision')
    fingerprint = inventory.get('map_fingerprints', {}).get(map_id)
    map_revision = (f'map:{fingerprint}' if isinstance(fingerprint, str) and SHA256.fullmatch(fingerprint)
                    else f'catalog:{revision}' if isinstance(revision, str) and SHA256.fullmatch(revision) else None)
    season_runtime = config.get('season_runtime') if mode == 'season' or paired_ctf_rules else None
    package = config.get('host_package')
    packaged_lua = Path(package)/'lua' if package else None
    if season_runtime:
        runtime_lua = Path(season_runtime)/'lua'
        network = runtime_lua/'network.lua'
    else:
        fixture = config.get('host_fixture')
        network = Path(fixture)/'network.lua' if fixture else None
        runtime_lua = packaged_lua
    runtime = None
    if network and network.is_file():
        digest = hashlib.sha256()
        digest.update(json.dumps(dict(
            adapter=inventory.get('training_adapters', {}).get(map_id),
            capture_limit=5 if season_runtime else None), sort_keys=True).encode())
        digest.update(hashlib.sha256(network.read_bytes()).digest())
        if runtime_lua:
            for path in sorted(runtime_lua.glob('*.lua')):
                if path.name != 'network.lua':
                    digest.update(path.name.encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
        if season_runtime and packaged_lua:
            for name in ('objectives.lua', 'objective_layouts.lua', 'legacy_objective_layouts.lua'):
                path = packaged_lua/name
                if path.is_file():
                    digest.update(name.encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
        runtime = digest.hexdigest()
    return dict(map_revision=map_revision, runtime_revision=runtime)


def new_run_provenance(output):
    try:
        request = json.loads((output/'request.json').read_bytes())
    except FileNotFoundError:
        return None
    return request.get('provenance')


def past_runs(output, mode, map_id='HighOctane2026', *, require_runtime=False, aim_calibration=False, provenance=None):
    if output.parent.name != 'DashboardRuns':
        return
    current = new_run_provenance(output) if provenance is None else provenance
    for folder in sorted(output.parent.iterdir()):
        if not RUN_ID.fullmatch(folder.name) or folder == output:
            continue
        try:
            request = json.loads((folder/'request.json').read_bytes())
            if request.get('evaluation') or request.get('mode') == 'benchmark':
                continue
            if bool(request.get('aim_calibration')) != aim_calibration:
                continue
            if current is not None:
                previous = request.get('provenance') or {}
                if not current.get('map_revision') or current['map_revision'] != previous.get('map_revision'):
                    continue
                if require_runtime and (not current.get('runtime_revision')
                                        or current['runtime_revision'] != previous.get('runtime_revision')):
                    continue
            if (mode is None or request['mode'] == mode) and request.get('map', 'HighOctane2026') == map_id:
                yield folder.name, request, json.loads((folder/'progress.json').read_bytes())
        except FileNotFoundError:
            continue


def flythrough_result(data, row):
    if row.get('pass_runup_cm', 0) <= 0:
        return False
    if data['configuration'].get('movement') == MOVEMENT:
        return True
    if row.get('recovered') is not False:
        return False
    if row.get('entered_flythrough') is True:
        return True
    if not row.get('trace'):
        return False
    # Older passes did not store entered_flythrough. Their trace records
    # whether the bot reached the fly-through segment of the route.
    try:
        with Path(row['trace']).open(encoding='utf-8') as source:
            return any(line.rstrip().endswith(',flythrough') for line in source)
    except FileNotFoundError:
        return False
