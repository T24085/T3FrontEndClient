"""Compare bounded native aim settings in side-swapped matches."""
from collections import defaultdict
import random
from statistics import mean


AIM_PROFILES = (10, 20)
AIM_EVIDENCE_VERSION = 2
MIN_SHOTS_PER_TEAM = 5
MIN_PAIRS = 4


def trial_assignment(index):
    pair, leg = divmod(index, 2)
    level = AIM_PROFILES[pair % len(AIM_PROFILES)]
    first_team = 1 + pair // len(AIM_PROFILES) % 2
    team = first_team if leg == 0 else 3 - first_team
    return pair + 1, team, level


def assess_trial(match):
    """Return the observed counts even when a game cannot enter the fit."""
    credited = {row['shot'] for row in match.get('combat', ()) if row['event'] == 'damage'}
    launches = defaultdict(set)
    for row in match.get('combat', ()):
        if row['event'] == 'launch':
            launches[row['shooter_team']].add(row['shot'])
    team_metrics = {str(team): dict(launched=len(launches[team]), damaged=len(launches[team] & credited),
                                   adjusted=sum(row.get('adjusted',0) for row in match.get('aim', ()) if row['team']==team))
                    for team in (1, 2)}
    candidate, native = (team_metrics[str(team)] for team in (match['candidate_team'],3-match['candidate_team']))
    reason = 'qualified'
    if not match.get('combat_complete'):
        reason = 'partial_combat'
    elif not match.get('aim'):
        reason = 'no_aim_decisions'
    elif native['adjusted']:
        reason = 'baseline_adjusted'
    elif not candidate['adjusted']:
        reason = 'no_adjustments'
    elif min(candidate['launched'],native['launched']) < MIN_SHOTS_PER_TEAM:
        reason = 'too_few_launches'
    return dict(reason=reason,teams=team_metrics)


def same_side_samples(pair, team):
    return pair[team][str(team)], pair[3-team][str(team)]


def same_side_gains(pair):
    gains = []
    for team in (1, 2):
        candidate, baseline = same_side_samples(pair, team)
        gains.append(candidate['damaged']/candidate['launched'] - baseline['damaged']/baseline['launched'])
    return gains


def paired_gain_interval(gains):
    if len(gains) < MIN_PAIRS:
        return None
    rng = random.Random(2026)
    margins = [mean(pair) for pair in gains]
    draws = sorted(mean(rng.choices(margins,k=len(margins))) for _ in range(2000))
    return [draws[50],draws[1949]]


def benchmark_aim_report(matches):
    """Summarize held-out games independently from calibration and selection."""
    pairs = defaultdict(dict)
    for row in matches:
        pairs[row['benchmark_pair']][row['candidate_team']] = row.get('benchmark_aim_observations')
    complete = [pair for pair in pairs.values() if set(pair) == {1, 2}]
    qualified = [{team: row['teams'] for team, row in pair.items()} for pair in complete
                 if all(row and row['reason']=='qualified' for row in pair.values())]
    gains = [same_side_gains(pair) for pair in qualified]
    sides = []
    for team in (1, 2):
        arms = dict(candidate=dict(damaged=0, launched=0), baseline=dict(damaged=0, launched=0))
        for pair in qualified:
            for total, sample in zip(arms.values(), same_side_samples(pair, team)):
                total['damaged'] += sample['damaged']
                total['launched'] += sample['launched']
        sides.append(dict(team=team, **arms,
                          mean_gain=mean(pair[team-1] for pair in gains) if gains else None))
    return dict(sides=sides, qualified_pairs=len(qualified), excluded_pairs=len(complete)-len(qualified),
                interval95=paired_gain_interval(gains), min_interval_pairs=MIN_PAIRS)


def calibration_report(batches):
    """A profile must improve both sides across several complete pairs."""
    profiles = defaultdict(list)
    for matches in batches:
        pairs = defaultdict(dict)
        for row in matches:
            if row.get('aim_pair') and row.get('aim_sample') and row.get('aim_evidence_version')==AIM_EVIDENCE_VERSION:
                pairs[row['aim_pair']][row['candidate_team']] = row
        for pair in pairs.values():
            if set(pair) != {1, 2} or pair[1]['aim_level'] != pair[2]['aim_level']:
                continue
            gains = same_side_gains({team: row['aim_sample'] for team, row in pair.items()})
            profiles[pair[1]['aim_level']].append(gains)
    comparisons = []
    for level in AIM_PROFILES:
        pairs = profiles[level]
        side_gain = [mean(gain) for gain in zip(*pairs)]
        interval = paired_gain_interval(pairs)
        comparisons.append(dict(level=level, pairs=len(pairs), gains=side_gain,
                                interval95=interval, eligible=bool(interval and interval[0]>0 and min(side_gain)>0)))
    best = max((row for row in comparisons if row['eligible']),
               key=lambda row: (mean(row['gains']), -row['level']), default=None)
    return dict(profiles=comparisons, selected=best['level'] if best else 0,
                min_pairs=MIN_PAIRS, same_side=True)
