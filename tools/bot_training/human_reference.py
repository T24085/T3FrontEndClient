"""Import actively played movement recordings as map-specific reference measurements."""
import argparse
import csv
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import median, quantiles

from learning_history import request_provenance
from practice import training_maps
from summarize import summarize
from train import publish


def measure(path):
    summary = summarize(path)
    if summary['recorded_seconds'] < 15 or summary['movement_samples'] < 100:
        raise ValueError(f'{path.name} needs at least 15 seconds of recording and 100 active movement samples.')
    active = air = jog = 0
    takeoffs, speeds = [], []
    previous = None
    with path.open(encoding='ascii', newline='') as stream:
        for raw in csv.DictReader(stream):
            row = {key:float(value) for key,value in raw.items()}
            if previous and previous['segment'] == row['segment']:
                dt = row['time_s']-previous['time_s']
                speed = .036*math.hypot(previous['vx_cm_s'],previous['vy_cm_s'])
                if 0 < dt <= .25 and speed >= 3:
                    speeds.append(speed)
                    active += dt
                    air += dt if not previous['grounded'] else 0
                    jog += dt if previous['grounded'] and not (previous['ski_requested'] or previous['jet_pressed']) else 0
                if 0 < dt <= .25 and previous['grounded'] and not row['grounded'] and row['jet_pressed']:
                    takeoffs.append(previous['energy'])
            previous = row
    if active < 8 or not takeoffs:
        raise ValueError(f'{path.name} needs at least eight seconds of actual travel and a jet takeoff.')
    return dict(active_seconds=round(active,2),airborne_ratio=round(air/active,3),grounded_jog_ratio=round(jog/active,3),
                median_kmh=round(median(speeds),1),takeoff_energy=takeoffs)


def reference_file(config, map_id):
    return Path(config['runs']).resolve().parent/'HumanMovementReferences'/f'{map_id}.json'


def load_reference(config, map_id):
    if 'runs' not in config or not config.get('map_catalog'):
        return {}
    path = reference_file(config,map_id)
    if not path.is_file():
        return {}
    data = json.loads(path.read_bytes())
    revision = request_provenance(config,map_id,'flight')['map_revision']
    if not revision or data['map_revision'] != revision or len(data['recordings']) < 3:
        return {}
    return data['summary']


def import_recordings(config, map_id, paths):
    revision = request_provenance(config,map_id,'flight')['map_revision']
    if not revision:
        raise ValueError('The map needs a verified catalog revision before importing references.')
    path = reference_file(config,map_id)
    old = json.loads(path.read_bytes()) if path.is_file() else {}
    data = dict(map=map_id,map_revision=revision,recordings=old.get('recordings',{}) if old.get('map_revision') == revision else {})
    for file in paths:
        digest = sha256(file.read_bytes()).hexdigest()
        if digest not in data['recordings']:
            data['recordings'][digest] = measure(file)
    sessions = list(data['recordings'].values())
    reserve = [energy for recording in sessions for energy in recording['takeoff_energy']]
    lower_quartile = quantiles(reserve,n=4,method='inclusive')[0] if len(reserve)>1 else reserve[0]
    data['summary'] = dict(recordings=len(sessions), grounded_jog_ratio=round(median(entry['grounded_jog_ratio'] for entry in sessions),3),
                           median_kmh=round(median(entry['median_kmh'] for entry in sessions),1),
                           airborne_ratio=round(median(entry['airborne_ratio'] for entry in sessions),3),
                           jet_reserve=round(max(20,min(38,lower_quartile)),1))
    path.parent.mkdir(parents=True, exist_ok=True)
    publish(path,json.dumps(data,indent=2)+'\n')
    return data['summary']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path)
    parser.add_argument('map')
    parser.add_argument('recordings',nargs='+',type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_bytes())
    if args.map not in training_maps(config):
        parser.error('Choose an installed training map.')
    print(json.dumps(import_recordings(config,args.map,args.recordings),indent=2))
