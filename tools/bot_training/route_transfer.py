"""Pool compatible capper evidence across local training modes."""
from collections import Counter, defaultdict
from itertools import product
import json
from pathlib import Path

from batch import select
from learning_history import flythrough_result, new_run_provenance, past_runs
from practice import MAP


def route_key(policy, runup, guidance, layout=None):
    if not isinstance(policy, dict) or not runup or not guidance or not policy.get('flank'):
        return None
    return (layout, runup, guidance, *(policy[field] for field in ('pulse', 'period', 'ski', 'turn')),
            1 if policy['flank'] > 0 else -1)


def guided_evidence(matches, source, by_key):
    for match in matches:
        sides = {bot['bot']: bot['team'] for bot in match.get('bots', ())}
        for row in match.get('guided_routes', ()):
            if row.get('outcome') not in ('miss', 'grab', 'capture'):
                continue
            name = by_key.get(route_key(row['policy'], row['runup_cm'], row['guidance'], row.get('layout')))
            if name:
                yield dict(route=name, team=row.get('team', sides.get(row.get('bot'))), contact=row['outcome'] != 'miss',
                           contact_kmh=row['pickup_kmh'], homeward_kmh=row['homeward_kmh'],
                           captured=row['outcome'] == 'capture', skiing=row['skiing'],
                           approach_entry_kmh=row.get('approach_entry_kmh'),
                           approach_peak_kmh=row.get('approach_peak_kmh'),
                           escape_seconds=row.get('escape_seconds'),
                           pass_gap_m=row.get('pass_gap_m'), pass_speed_kmh=row.get('pass_speed_kmh'),
                           evidence='live', source=source)


def trial_pickup_evidence(row):
    return dict(contact=bool(row['pickup']), contact_kmh=row.get('grab_kmh'),
                homeward_kmh=row.get('grab_homeward_kmh'), captured=bool(row['capture']),
                skiing=bool(row.get('skiing_flythrough_grab')),
                approach_entry_kmh=row.get('approach_entry_kmh'), approach_peak_kmh=row.get('approach_peak_kmh'))


def candidate_keys(candidates):
    return {route_key(row['policy'], row['pass_runup_cm'], row['guidance'], row.get('layout')): row['approach_route']
            for row in candidates}


def route_evidence(output, map_id, candidates):
    by_key = candidate_keys(candidates)
    if output.parent.name != 'DashboardRuns':
        return []
    root = output.parent.parent
    checkpoints = [(name, data) for name, _, data in past_runs(output, None, map_id)]
    if map_id == MAP and new_run_provenance(output) is None:
        for path in sorted(root.glob('Campaign-*/progress.json')):
            data = json.loads(path.read_bytes())
            if data.get('map', MAP) == map_id:
                checkpoints.append((path.parent.name, data))
    evidence = []
    for source, data in checkpoints:
        for index, wave in enumerate(data.get('waves', ())):
            plans = data.get('routes', [])
            settings = wave.get('settings') or (plans[index] if index < len(plans) else ())
            if not isinstance(settings, list) or len(settings) != len(wave['results']):
                continue
            for row, setup in zip(wave['results'], settings):
                if row.get('route') != setup.get('approach_route'):
                    continue
                name = by_key.get(route_key(setup.get('policy'), setup.get('pass_runup_cm'),
                                            setup.get('guidance'), setup.get('layout')))
                if name:
                    evidence.append(dict(row, route=name, evidence='screening', source=source))
        configuration = data.get('configuration', {})
        for row in data.get('attempts', ()):
            if row.get('held_out') or not flythrough_result(data, row) or row.get('recovered'):
                continue
            setup = configuration.get('routes', {}).get(row.get('approach_route'), {})
            name = by_key.get(route_key(row.get('policy'), row.get('pass_runup_cm'),
                                        row.get('pass_guidance') or setup.get('guidance')))
            if name:
                evidence.append(dict(trial_pickup_evidence(row), route=name, evidence='live', source=source))
        evidence.extend(guided_evidence(data.get('matches', ()), source, by_key))
    return evidence


def screening_candidates(root):
    source = Path(root) / 'Campaign-FlagPassSpeed500/progress.json'
    catalog = json.loads(source.read_bytes())['configuration']['routes']
    return [dict(approach_route=name, policy=route['policy'], pass_runup_cm=route['runup_cm'],
                 guidance=route['guidance'], campaign_attempt=None) for name, route in catalog.items()]


def exploratory_routes():
    for side, (runup, guidance, adjustment), pulse in product(
            ('left', 'right'), ((8500, 3, 3), (11000, 4, 0), (12000, 5, -3)), (.16, .36)):
        direction = -1 if side == 'left' else 1
        name = f'{side}_{runup // 100}m_{round(pulse * 1000)}ms_jet'
        policy = dict(pulse=pulse, period=1.8, ski=1, turn=direction * adjustment,
                      approach_cm=2200, flank=direction)
        yield dict(approach_route=name, policy=policy, pass_runup_cm=runup,
                   guidance=guidance, campaign_attempt=None, exploratory=True)


def flank_routes():
    for (layout, runup, guidance), pulse, side in product(
            (('wide_flank', 9500, 3), ('back_cut', 16000, 4),
             ('wide_flank', 13000, 4), ('back_cut', 20500, 5)), (.25, .36), ('left', 'right')):
        direction = -1 if side == 'left' else 1
        name = f'{side}_{layout}_{runup // 100}m_{round(pulse * 1000)}ms_jet'
        policy = dict(pulse=pulse, period=1.8, ski=1, turn=0, approach_cm=2200, flank=direction)
        yield dict(approach_route=name, layout=layout, policy=policy, pass_runup_cm=runup, guidance=guidance)


def flank_assignments(roster, candidates, evidence, score, rng):
    by_name = {route['approach_route']: route for route in candidates}
    attempts = Counter((row.get('team'), row['route']) for row in evidence if row['evidence'] == 'live')
    minimum_per_side = 2
    assignments = {}
    for team in (1, 2):
        history = {name: [] for name in by_name}
        for row in evidence:
            if row.get('team') in (None, team) and row['route'] in history:
                history[row['route']].append(row)
        unused = history.copy()
        directions = set()
        for slot, entry in enumerate(roster, 1):
            if entry != (team, 'Capper'):
                continue
            if not unused:
                unused = history.copy()
            insufficient = [name for name in unused
                            if min(attempts[1, name], attempts[2, name]) < minimum_per_side]
            if insufficient:
                minimum = min(min(attempts[1, name], attempts[2, name]) for name in insufficient)
                least_sampled = [name for name in insufficient if min(attempts[1, name], attempts[2, name]) == minimum]
                distinct = [name for name in least_sampled if by_name[name]['policy']['flank'] not in directions]
                name = rng.choice(distinct or least_sampled)
            else:
                name = select(unused, rng, next(iter(unused)), score)
            assignments[slot] = by_name[name]
            directions.add(by_name[name]['policy']['flank'])
            unused.pop(name)
    return assignments


def ranked_routes(candidates, evidence, score):
    """Compare a route's repeatability, with a separate live-match average."""
    grouped = defaultdict(lambda: defaultdict(list))
    for row in evidence:
        grouped[row['route']][row['evidence']].append(score(row))

    def rating(name):
        tests = grouped[name]
        screening = tests['screening']
        live = tests['live']
        # Shrink small trials towards a zero-score attempt rather than promote outliers.
        screened = sum(screening) / (len(screening) + 3)
        confirmed = sum(live) / (len(live) + 3)
        screening_weight = 1 - .5 * len(live) / (len(live) + 3)
        return screening_weight * screened + confirmed

    ranked = [row for row in candidates if any(
        grouped[row['approach_route']].values()) and rating(row['approach_route']) > 0]
    return sorted(ranked, key=lambda row: rating(row['approach_route']), reverse=True)


def guided_assignments(roster, candidates, evidence, score, match, rng):
    probes = [route for route in candidates if route.get('exploratory')]
    groups = [(team, slots) for team in (1, 2)
              if (slots := [slot for slot, entry in enumerate(roster, 1) if entry == (team, 'Capper')])]
    if not groups:
        return {}
    probing_team = groups[(match // 4) % len(groups)][0] if probes and match % 4 == 3 else None
    assignments = {}
    for team, slots in groups:
        own = [row for row in evidence if row.get('team') in (None, team)]
        ranked = ranked_routes(candidates, own, score)
        if probes and (team == probing_team or not ranked):
            counts = Counter(row['route'] for row in own if row['evidence'] == 'live')
            least_tested = min(counts[route['approach_route']] for route in probes)
            choice = rng.choice([route for route in probes if counts[route['approach_route']] == least_tested])
        elif ranked:
            choice = ranked[(match+team-1) % min(4, len(ranked))]
        else:
            continue
        assignments[slots[match % len(slots)]] = choice
    return assignments
