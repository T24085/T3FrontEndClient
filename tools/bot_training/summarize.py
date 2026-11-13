"""Check a demonstration file and report how much usable movement it contains."""
import argparse
import csv
import json
import math
from pathlib import Path

from practice import FIELDS


def summarize(path):
    samples = active = segments = ski = jet = 0
    elapsed = 0.0
    previous = None
    with path.open(encoding='ascii', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS.split(','):
            raise ValueError('Unexpected movement CSV header.')
        for raw in reader:
            if set(raw) != set(reader.fieldnames) or any(value is None for value in raw.values()):
                raise ValueError(f'Incomplete sample on line {reader.line_num}.')
            row = {key: float(value) for key, value in raw.items()}
            if not all(map(math.isfinite, row.values())):
                raise ValueError(f'Invalid numeric sample on line {reader.line_num}.')
            if (row['team'] not in (1, 2) or row['segment'] < 1 or not row['segment'].is_integer()
                    or any(row[key] not in (0, 1) for key in ('grounded', 'ski_requested', 'jet_pressed'))):
                raise ValueError(f'Invalid discrete state on line {reader.line_num}.')
            if previous is None or row['segment'] > previous['segment']:
                segments += 1
            else:
                delta = row['time_s'] - previous['time_s']
                if row['segment'] < previous['segment'] or delta <= 0:
                    raise ValueError(f'Samples are out of order on line {reader.line_num}.')
                if delta <= .25:
                    elapsed += delta
            previous = row
            samples += 1
            active += math.hypot(row['move_x'], row['move_y']) > .01
            ski += int(row['ski_requested'])
            jet += int(row['jet_pressed'])
    return {'samples': samples, 'segments': segments, 'recorded_seconds': round(elapsed, 2),
            'movement_samples': active, 'ski_samples': ski, 'jet_samples': jet}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.recording), indent=2))
