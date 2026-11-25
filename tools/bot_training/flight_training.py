"""Isolated movement drills with paired tests at the same native starting positions."""
import csv
import json
import math
from statistics import median
import time

from dashboard_run import TeamTrainer
from learning_history import past_runs
from practice import HERE, MAP, MAX_TRAINING_BOTS, NativeMemoryBusy, check_between_matches, start, training_wait
from team_waves import evidence_path, ready_receipt, validate_reset, wave_plan
from train import publish, read_ready, replace_once


LEGACY_SCENARIO = 'flight-fundamentals-v1'
SCENARIO = 'flight-fundamentals-v2'
COURSE_M = 160
HILL_M = 80
WALK = 'run-only'
PROFILES = {
    WALK: dict(ski=0, pulse=0, period=2),
    'ski-only': dict(ski=1, pulse=0, period=2),
    'short-jets': dict(ski=1, pulse=.40, period=1.8),
    'steady-jets': dict(ski=1, pulse=.70, period=2.6),
    'long-jets': dict(ski=1, pulse=1.05, period=3.5),
}
COURSE_LABELS = {'straight': 'Straight flight', 'downhill': 'Downhill momentum', 'uphill': 'Uphill jets',
                 'recovery': 'Low-energy recovery'}
HILL_PROFILES = {
    'downhill': {WALK: PROFILES[WALK], 'ski-only': PROFILES['ski-only'],
                 'ski-delayed': dict(ski=1, pulse=0, period=2, ski_delay=1.25)},
    'uphill': {name: profile for name, profile in PROFILES.items() if name != WALK},
}
JET_PROFILES = {name: settings for name, settings in PROFILES.items() if settings['pulse'] > 0}
STRICT_SKI_PROFILES = {
    'ski-only': PROFILES['ski-only'],
    'ski-gentle': PROFILES['ski-only'] | {'steer_cap': .20},
    'ski-tight': PROFILES['ski-only'] | {'steer_cap': .42},
}
MAX_JOG_RATIO = .05


def profiles_for(course, strict):
    if strict:
        return STRICT_SKI_PROFILES if course == 'downhill' else JET_PROFILES
    return HILL_PROFILES.get(course, PROFILES)


def baseline_for(course, strict=False):
    if strict:
        return 'ski-only' if course == 'downhill' else 'steady-jets'
    return 'ski-only' if course == 'uphill' else WALK


def qualified_flight_transfer(output, map_id, provenance=None):
    """Freeze proven per-course inputs for a new match campaign on the same map revision."""
    selected = {}
    for source, _, report in past_runs(output, 'flight', map_id, provenance=provenance):
        course = report.get('course', 'straight')
        comparison = report.get('comparison') or {}
        name = comparison.get('profile')
        if (report.get('scenario') == SCENARIO and course in ('straight','uphill','recovery')
                and comparison.get('qualified') and name in JET_PROFILES):
            selected[course] = dict(source=source,profile=name,**JET_PROFILES[name])
    return selected


def validate_flight(bots, seconds, course='straight'):
    if type(bots) is not int or not 4 <= bots <= MAX_TRAINING_BOTS or bots % 2:
        raise ValueError(f'Choose an even number from 4 to {MAX_TRAINING_BOTS} bots per flight wave.')
    if type(seconds) is not int or not 30 <= seconds <= 90:
        raise ValueError('Choose 30–90 seconds per flight wave.')
    if not isinstance(course, str) or course not in COURSE_LABELS:
        raise ValueError('Choose a flight course.')


def measure_flight(trace, course='straight', strict=False):
    with trace.open(newline='', encoding='utf-8') as source:
        rows = list(csv.DictReader(source))
        if len(rows) < 2:
            raise ValueError('Flight trace has incomplete movement evidence.')
        origin = tuple(float(rows[0][axis]) for axis in ('x_cm', 'y_cm', 'z_cm'))
        heading = float(rows[0]['heading_deg'])
        frames = [
            (float(row['seconds']), float(row['forward_m']),
             .036*math.hypot(float(row['vx_cm_s']), float(row['vy_cm_s'])),
             row['grounded'] == '0', row['jet'] == '1', row['ski'] == '1', float(row['energy']))
            for row in rows
        ]
    if not all(map(math.isfinite, (*origin, heading))) or any(not all(map(math.isfinite, frame)) for frame in frames):
        raise ValueError('Flight trace has incomplete movement evidence.')
    initial_energy = frames[0][-1]
    valid_energy = 0 <= initial_energy <= 48 if course == 'recovery' else initial_energy >= 98
    if abs(frames[0][0]) > .001 or abs(frames[0][1]) > .05 or not valid_energy:
        raise ValueError('Flight trace did not start from the verified starting state.')
    air_forward = air_time = air_streak = longest_air = slow = jet = ski = jog = measured = 0
    speeds = []
    for previous, current in zip(frames, frames[1:]):
        interval = current[0]-previous[0]
        if interval < 0:
            raise ValueError('Flight trace timestamps went backwards.')
        if not 0 < interval <= .75:
            air_streak = 0
            continue
        speeds.append(previous[2])
        measured += interval
        if not any(previous[3:6]) and previous[2] >= 3:
            jog += interval
        slow += interval if previous[2] < 15 else 0
        jet += interval if previous[4] else 0
        ski += interval if previous[5] else 0
        if previous[3] and current[3]:
            air_time += interval
            air_streak += interval
            longest_air = max(longest_air, air_streak)
            air_forward += min(max(0, current[1]-previous[1]), 110*interval)
        else:
            air_streak = 0
    if not speeds:
        raise ValueError('Flight trace has no usable movement intervals.')
    forward = max(0, frames[-1][1])
    speed = median(speeds)
    score = (.42*min(forward/COURSE_M, 1) + .20*min(speed/90, 1) +
             .28*min(air_forward/110, 1) + .10*min(longest_air/2.5, 1))
    result = dict(start_cm=origin, heading_deg=heading, seconds=round(frames[-1][0], 3), forward_m=round(forward, 2), median_kmh=round(speed, 2),
                peak_kmh=round(max(speeds), 2), airborne_m=round(air_forward, 2), airborne_seconds=round(air_time, 2),
                longest_air_seconds=round(longest_air, 2), slow_seconds=round(slow, 2), jet_seconds=round(jet, 2),
                ski_seconds=round(ski, 2), score=round(score, 5))
    if course in HILL_PROFILES:
        result.update(measure_hill(rows, frames, course, heading, forward))
    elif course == 'recovery':
        result.update(measure_recovery(rows, frames, heading, forward))
    if strict:
        fraction = jog/measured
        result.update(ground_jog_seconds=round(jog, 2), ground_jog_ratio=round(fraction, 4),
                      score=round(result['score']*max(0, 1-5*fraction), 5))
    return result


def measure_recovery(rows, frames, heading, forward):
    angle = math.radians(heading)
    velocity = [(float(row['vx_cm_s']), float(row['vy_cm_s'])) for row in rows]
    along = [.036*(x*math.cos(angle)+y*math.sin(angle)) for x, y in velocity]
    cross = [.036*(-x*math.sin(angle)+y*math.cos(angle)) for x, y in velocity]
    terrain = float(rows[0]['course_drop_m'])
    if not math.isfinite(terrain) or terrain < 3 or abs(cross[0]) < 20 or along[0] > 12:
        raise ValueError('The recovery trace did not begin with a verified sideways shove on a slope.')
    stable_since = None
    recovery_seconds = None
    for index, (frame, forward_kmh, lateral_kmh) in enumerate(zip(frames, along, cross, strict=True)):
        if index and frame[0]-frames[index-1][0] > .75:
            stable_since = None
        if forward_kmh >= 45 and abs(lateral_kmh) <= forward_kmh*.45 and (frame[3] or frame[5]):
            if stable_since is None:
                stable_since = frame[0]
            if frame[0]-stable_since >= .5 and frame[1] > 5:
                recovery_seconds = frame[0]
                break
        else:
            stable_since = None
    recovered = recovery_seconds is not None
    result = .4*min(forward/HILL_M,1) + (.6*max(.1, 1-recovery_seconds/15) if recovered else 0)
    return dict(recovery_seconds=recovery_seconds, recovered=recovered, initial_energy=round(frames[0][-1],2),
                initial_lateral_kmh=round(abs(cross[0]),2), score=round(result,5))


def measure_hill(rows, frames, course, heading, forward):
    angle = math.radians(heading)
    along = [.036*(float(row['vx_cm_s'])*math.cos(angle) + float(row['vy_cm_s'])*math.sin(angle)) for row in rows]
    drop = float(rows[0]['course_drop_m'])
    cross = float(rows[-1]['cross_m'])
    height_gain = (float(rows[-1]['z_cm'])-float(rows[0]['z_cm']))/100
    if drop < 8 or not all(map(math.isfinite, (drop, cross, height_gain))):
        raise ValueError('Hill course has no verified terrain grade.')
    finished = forward >= HILL_M-.01 and abs(cross) <= 12
    entry = None
    for index, (before, after) in enumerate(zip(frames, frames[1:])):
        if before[1] < 20 <= after[1] and 0 < after[0]-before[0] <= .75:
            fraction = (20-before[1])/(after[1]-before[1])
            entry = max(0, along[index]+fraction*(along[index+1]-along[index]))
            break
    exit_speed = max(0, along[-1]) if finished else None
    retention = exit_speed/entry if exit_speed is not None and entry and entry >= 5 else None
    forward_jet = 0
    for before, after in zip(frames, frames[1:]):
        interval = after[0]-before[0]
        if before[4] and 0 < interval <= .75:
            forward_jet += min(max(0, after[1]-before[1]), 110*interval)
    progress = min(forward/HILL_M, 1)
    if course == 'downhill':
        score = .50*progress + .32*min((exit_speed or 0)/95,1) + .18*min(retention or 0,1)
    else:
        score = (.55*progress + .20*min(max(0,height_gain)/drop,1)
                 + .15*min(forward_jet/35,1) + .10*min((exit_speed or 0)/65,1))
    return dict(finished=finished, terrain_drop_m=round(drop,2), elevation_gain_m=round(height_gain,2),
                entry_kmh=round(entry,2) if entry is not None else None,
                exit_kmh=round(exit_speed,2) if exit_speed is not None else None,
                retention=round(retention,3) if retention is not None else None,
                jet_forward_m=round(forward_jet,2), score=round(score,5))


def choose_profile(waves, course='straight', strict=False):
    ranked = []
    trials = [row for wave in waves for row in wave['bots']]
    available = profiles_for(course, strict)

    def demonstrated(row):
        if strict and row['ground_jog_ratio'] > MAX_JOG_RATIO:
            return False
        if course == 'recovery':
            return row['recovered']
        if course == 'downhill':
            return row['finished'] and row['ski_seconds'] > 0
        if course == 'uphill':
            return row['jet_forward_m'] >= 8 and row['elevation_gain_m'] > 3 and row['forward_m'] >= 40
        return row['jet_seconds'] > 0 and row['airborne_m'] >= 10

    for name, settings in available.items():
        if name == baseline_for(course, strict) or (course == 'straight' and not settings['pulse']):
            continue
        sides = [[row for row in trials if row['team'] == team and row['profile'] == name] for team in (1, 2)]
        if all(any(demonstrated(row) for row in side) for side in sides):
            ranked.append((min(median(row['score'] for row in side) for side in sides), name))
    return max(ranked, default=(0, None))[1]


def assignments(index, count, candidate, evaluation_start, course='straight', strict=False):
    names = tuple(profiles_for(course, strict))
    side = count//2
    if candidate and index >= evaluation_start:
        baseline = baseline_for(course, strict)
        return tuple(candidate if (slot % side+index-evaluation_start) % 2 else baseline for slot in range(count))
    return tuple(names[(index*side+slot % side) % len(names)] for slot in range(count))


def flight_comparison(waves, candidate, course='straight', strict=False):
    if not candidate or len(waves) != 2:
        return None
    sides = []
    baseline = baseline_for(course, strict)
    for team in (1, 2):
        paired = {}
        for wave in waves:
            for bot in wave['bots']:
                if bot['team'] == team:
                    paired.setdefault(bot['bot'], {})[bot['profile']] = bot
        pairs = [(row[baseline], row[candidate]) for row in paired.values()
                 if baseline in row and candidate in row
                 and math.dist(row[baseline]['start_cm'], row[candidate]['start_cm']) <= (200 if course == 'recovery' else 35 if course == 'uphill' else 1)
                 and abs(row[baseline]['heading_deg']-row[candidate]['heading_deg']) <= .1
                 and (course not in HILL_PROFILES or abs(row[baseline]['terrain_drop_m']-row[candidate]['terrain_drop_m']) <= .15)
                 and (course != 'recovery' or abs(row[baseline]['initial_energy']-row[candidate]['initial_energy']) <= 8)]
        if not pairs:
            return None
        gain = median(test['score']-base['score'] for base, test in pairs)
        side = dict(team=team, pairs=len(pairs), gain=round(gain, 4),
                          baseline_kmh=round(median(base['median_kmh'] for base, _ in pairs), 1),
                          candidate_kmh=round(median(test['median_kmh'] for _, test in pairs), 1),
                          candidate_air_m=round(median(test['airborne_m'] for _, test in pairs), 1),
                          candidate_jet_s=round(median(test['jet_seconds'] for _, test in pairs), 2))
        if strict:
            side['candidate_max_jog_ratio'] = max(test['ground_jog_ratio'] for _, test in pairs)
        if course == 'recovery':
            recovery = [test['recovery_seconds'] for _, test in pairs if test['recovered']]
            side.update(baseline_finish=sum(base['recovered'] for base, _ in pairs), candidate_finish=len(recovery),
                        recovery_seconds=round(median(recovery),2) if recovery else None)
        if course in HILL_PROFILES:
            baseline_exit = [base['exit_kmh'] for base, _ in pairs if base['exit_kmh'] is not None]
            candidate_exit = [test['exit_kmh'] for _, test in pairs if test['exit_kmh'] is not None]
            retained = [test['retention'] for _, test in pairs if test['retention'] is not None]
            side.update(baseline_finish=sum(base['finished'] for base, _ in pairs),
                        candidate_finish=sum(test['finished'] for _, test in pairs),
                        baseline_exit=round(median(baseline_exit),1) if baseline_exit else None,
                        candidate_exit=round(median(candidate_exit),1) if candidate_exit else None,
                        retention=round(median(retained),2) if retained else None,
                        elevation=round(median(test['elevation_gain_m'] for _, test in pairs),1),
                        jet_forward=round(median(test['jet_forward_m'] for _, test in pairs),1))
        sides.append(side)

    def passed(side):
        if side['pairs'] < 2 or side['gain'] < .05:
            return False
        if strict and side['candidate_max_jog_ratio'] > MAX_JOG_RATIO:
            return False
        if course == 'recovery':
            return side['candidate_finish']*2 >= side['pairs'] and side['recovery_seconds'] <= 9
        if course == 'downhill':
            return (side['candidate_finish']*2 >= side['pairs'] and (side['retention'] or 0) >= .85
                    and (side['candidate_exit'] or 0) > (side['baseline_exit'] or 0)+5)
        if course == 'uphill':
            return side['candidate_finish']*2 >= side['pairs'] and side['elevation'] >= 8 and side['jet_forward'] >= 8
        return side['candidate_kmh'] > side['baseline_kmh'] + 2 and side['candidate_air_m'] >= 20 and side['candidate_jet_s'] > 0

    return dict(profile=candidate, baseline=baseline, sides=sides, qualified=all(map(passed,sides)))


class FlightTrainer(TeamTrainer):
    match_script = 'flight_trials.lua'
    verify_start = True
    record_combat = False

    def __init__(self, selection, seconds, testing, course='straight', strict=False):
        side = ('Capper',)*(len(selection)//2)
        super().__init__(side, side, seconds)
        self.selection = selection
        self.testing = testing
        self.course = course
        self.strict_flight = strict
        profiles = profiles_for(course, strict)
        self.flight_plan = {slot: profiles[profile] for slot, profile in enumerate(selection, 1)}

    def instrument(self, text, out):
        text = super().instrument(text, out)
        first_plan = wave_plan(self, 1).removeprefix('return ').strip()
        length = COURSE_M if self.course == 'straight' else HILL_M
        hill = (f'hill_kind={json.dumps(self.course)},hill_script={json.dumps((HERE/"hill_course.lua").as_posix())},'
                if self.course != 'straight' else '')
        strict = 'strict_flight=true,' if self.strict_flight else ''
        return replace_once(text, '  seconds=', f'  flight_plan=({first_plan}).flight_plan,course_m={length},{hill}{strict}seconds=')

    def read_match(self, out, process, wave=1):
        ready_receipt(self, out, process, wave)
        if wave == 1:
            self.wait(out, process, lambda _: read_ready(out/'team-ready.csv'), 420)
            validate_reset(out, wave, self.bot_count)
            self.announce_ready()
        receipt = self.wait(out, process, lambda _: read_ready(evidence_path(out, wave, 'flight-complete.csv')), 150)
        if receipt.strip() != f'{wave},{self.bot_count}':
            raise RuntimeError('Invalid native flight receipt.')
        bots = []
        for slot, (profile, (team, _)) in enumerate(zip(self.selection, self.roster, strict=True), 1):
            trace = evidence_path(out, wave, f'team-bot-{slot}-trace.csv')
            measured = measure_flight(trace, self.course, self.strict_flight)
            bots.append(dict(bot=slot, team=team, profile=profile, trace=str(trace), **measured))
        self.result = dict(bots=bots, testing=self.testing)


def flight_run(config, output, waves, seconds, bots, waves_per_launch, course='straight'):
    validate_flight(bots, seconds, course)
    path = output/'progress.json'
    expected = dict(scenario=SCENARIO, map=config.get('training_map', MAP), target=waves, seconds=seconds,
                    bots=bots, course_m=COURSE_M if course == 'straight' else HILL_M)
    initial = expected | {'waves': [], 'reset_fallbacks': []}
    if course != 'straight':
        initial['course'] = course
    report = json.loads(path.read_bytes()) if path.exists() else initial
    strict = report.get('scenario') != LEGACY_SCENARIO
    if not strict:
        expected['scenario'] = LEGACY_SCENARIO
    if any(report.get(key) != value for key, value in expected.items()) or report.get('course', 'straight') != course:
        raise ValueError('Flight setup changed. Start a new drill for different settings.')
    if course != 'straight':
        report['course'] = course
    saved = report['waves']
    evaluation_start = waves-2 if waves >= 3 else waves

    def prepare():
        index = len(saved)
        candidate = choose_profile(saved[:evaluation_start], course, strict) if index >= evaluation_start else None
        selection = assignments(index, bots, candidate, evaluation_start, course, strict)
        return FlightTrainer(selection, seconds, candidate, course, strict)

    def checkpoint(trainer):
        saved.append(trainer.result)
        report['comparison'] = flight_comparison(saved[evaluation_start:], trainer.testing, course, strict)
        publish(path, json.dumps(report, indent=2)+'\n')
        print(f'Flight waves saved: {len(saved)}/{waves}', flush=True)

    def announce_ready():
        if report.pop('waiting', None) is not None:
            publish(path, json.dumps(report, indent=2)+'\n')

    publish(path, json.dumps(report, indent=2)+'\n')
    wave_limit = 1 if report['reset_fallbacks'] else waves_per_launch
    while len(saved) < waves:
        check_between_matches()
        trainer = prepare()
        trainer.waves_per_launch = min(wave_limit, waves-len(saved))
        trainer.next_match, trainer.save_match = prepare, checkpoint
        trainer.announce_ready = announce_ready
        began = time.monotonic()
        try:
            start(config, trainer=trainer)
        except RuntimeError as exc:
            if isinstance(exc, NativeMemoryBusy) or type(exc).__name__ == 'NativeResourceBusy':
                if report.get('waiting') != str(exc):
                    report['waiting'] = str(exc)
                    publish(path, json.dumps(report, indent=2)+'\n')
                print(str(exc), flush=True)
                training_wait(20)
            elif wave_limit > 1 and 'training_reuse_unverified|' in str(exc):
                wave_limit = 1
                report['reset_fallbacks'].append(dict(after=len(saved), wall_seconds=round(time.monotonic()-began, 2)))
                publish(path, json.dumps(report, indent=2)+'\n')
                print('Flight reset could not be verified. Saved results are intact. Retrying with a fresh host.', flush=True)
            else:
                raise
