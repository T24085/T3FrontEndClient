"""Summarize public flight recordings separately from native training data."""

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from statistics import median


ROCKET = 'SpaceX webcast telemetry, archived by shahar603'
DRONE = 'UZH NeuroBEM'


def rocket_summary(content):
    data = json.loads(content)
    rows = [(float(t), float(speed), float(height)) for t, speed, height in
            zip(data['time'], data['velocity'], data['altitude'], strict=True)
            if speed is not None and height is not None and 0 <= float(t) <= 120]
    if not rows or any(not all(map(math.isfinite, row)) for row in rows):
        raise ValueError('No usable samples in the first 120 seconds.')
    return dict(source=ROCKET, samples=len(rows), sample_window_s=[rows[0][0], rows[-1][0]],
                speed_10s_bins=[dict(start_s=start, median_source_speed=median(speeds))
                                for start in range(0, 120, 10)
                                if (speeds := [speed for t, speed, _ in rows if start <= t < start + 10])])


def drone_summary(content):
    with io.StringIO(content.decode('utf-8-sig')) as source:
        reader = csv.reader(source)
        next(reader)  # The publisher documents column order in its dataset README.
        rows = [list(map(float, row)) for row in reader if row]
    if len(rows) < 2 or any(len(row) != 29 or not all(map(math.isfinite, row)) for row in rows):
        raise ValueError('Expected a processed NeuroBEM CSV with 29 finite columns.')
    windows = [(row, later) for row, later in zip(rows, rows[1:]) if 0 < later[0] - row[0] <= .05]
    if not windows:
        raise ValueError('No continuous samples in the drone recording.')
    return dict(source=DRONE, samples=len(rows), measured_seconds=round(sum(b[0] - a[0] for a, b in windows), 2),
                median_speed_kmh=round(3.6 * median(math.hypot(*a[14:17]) for a, _ in windows), 2),
                median_motor_rad_s=round(median(sum(a[20:24]) / 4 for a, _ in windows), 2),
                median_turn_rate_rad_s=round(median(math.hypot(*a[4:7]) for a, _ in windows), 3))


def native_summary(content):
    from dashboard_run import team_bot_metrics

    run = json.loads(content)
    results = []
    missing = 0
    for match in run['matches']:
        for bot in match['bots']:
            if bot['role'] != 'Capper':
                continue
            try:
                with Path(bot['trace']).open(newline='', encoding='utf-8-sig') as trace:
                    data = team_bot_metrics(list(csv.DictReader(trace)))
            except FileNotFoundError:
                missing += 1
                continue
            if 'fast_air_seconds' in data:
                results.append(data)
            else:
                missing += 1
    keys = ('median_kmh', 'airborne_seconds', 'jet_seconds', 'fast_air_seconds', 'longest_fast_air_seconds',
            'fast_glide_seconds', 'landing_speed_retained', 'landing_energy')
    metrics = {key: round(median(values), 2) for key in keys
               if (values := [row[key] for row in results if row[key] is not None])}
    return dict(source='TRIBES capper traces', map=run['map'], matches=len(run['matches']),
                capper_traces=len(results), unavailable_traces=missing,
                capper_traces_with_no_recorded_jets=sum(row['jet_seconds'] == 0 for row in results),
                per_capper_median=metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    readers = {'spacex': rocket_summary, 'neurobem': drone_summary, 'native-team': native_summary}
    parser.add_argument('format', choices=readers)
    parser.add_argument('file', type=Path)
    options = parser.parse_args()
    content = options.file.read_bytes()
    summary = readers[options.format](content)
    print(json.dumps(summary | {'input_sha256': hashlib.sha256(content).hexdigest()}, indent=2))


if __name__ == '__main__':
    main()
