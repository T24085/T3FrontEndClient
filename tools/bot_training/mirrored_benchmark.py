"""Freeze role tactics and compare them against a baseline in paired CTF games."""
from collections import defaultdict
import hashlib
import json
import random
from statistics import mean

from defense_learning import BASELINE


def freeze_tactics(roles, defense, offense):
    candidate, baseline, training_samples = {}, {}, {}
    for role in dict.fromkeys(roles):
        learned = defense.history.get(role, {}) | offense.history.get(role, {})
        if not learned:
            continue
        observed = {name: values for name, values in learned.items() if values}
        # Stable tie break, with the baseline retaining precedence on an exact tie.
        selected = max(observed, key=lambda name: (mean(observed[name]), name == BASELINE, name), default=BASELINE)
        candidate[role], baseline[role] = selected, BASELINE
        training_samples[role] = len(observed.get(selected, ()))
    strategy = dict(candidate=candidate, baseline=baseline, training_samples=training_samples)
    strategy['revision'] = hashlib.sha256(json.dumps(strategy, sort_keys=True).encode()).hexdigest()
    return strategy


def archived_opponents(batches, frozen, defense, offense):
    """Take fixed opponent tactics from compatible saved training matches."""
    result = [dict(label='Original tactics', tactics=frozen['baseline'])]
    known = set(defense.history) | set(offense.history)
    seen = {tuple(sorted(frozen['baseline'].items()))}
    for source, matches in reversed(list(batches)):
        for match in reversed(matches):
            assignments = match.get('defense_tactics', {}) | match.get('offense_tactics', {})
            tactics = dict(frozen['baseline'])
            for bot in match['bots']:
                role = bot['role']
                profile = assignments.get(str(bot['bot']))
                if bot['team'] == 1 and role in known and profile in (defense.history.get(role,{}) | offense.history.get(role,{})):
                    tactics[role] = profile
            fingerprint = tuple(sorted(tactics.items()))
            if fingerprint not in seen:
                result.append(dict(label=f'Saved lineup {len(result)}', source=source, tactics=tactics))
                seen.add(fingerprint)
                break
        if len(result) == 4:
            break
    return result


def pair_assignment(frozen, roster, completed, defense, offense):
    pair = completed // 2 + 1
    team = 1 + (completed + pair - 1) % 2
    assignments = {index: (role, frozen['candidate' if side == team else 'baseline'][role])
                   for index, (side, role) in enumerate(roster, 1) if role in frozen['candidate']}
    return (pair, team, {slot: plan for slot, plan in assignments.items() if plan[0] in defense.history},
            {slot: plan for slot, plan in assignments.items() if plan[0] in offense.history})


def paired_results(rows):
    pairs = defaultdict(dict)
    for row in rows:
        pair, side = row['benchmark_pair'], row['candidate_team']
        if side not in (1, 2) or side in pairs[pair]:
            raise ValueError('Duplicate or invalid benchmark side')
        candidate, baseline = (row['blue'], row['red']) if side == 1 else (row['red'], row['blue'])
        leg = dict(candidate=candidate, baseline=baseline)
        if 'spawn_fingerprint' in row:
            leg.update(spawn_fingerprint=row['spawn_fingerprint'], opponent=row['opponent'])
        pairs[pair][side] = leg
    completed, excluded = [], 0
    for pair, legs in sorted(pairs.items()):
        if len(legs) != 2:
            continue
        if 'spawn_fingerprint' in legs[1] or 'spawn_fingerprint' in legs[2]:
            if (not legs[1].get('spawn_fingerprint') or legs[1].get('spawn_fingerprint') != legs[2].get('spawn_fingerprint')
                    or legs[1].get('opponent') != legs[2].get('opponent')):
                excluded += 1
                continue
        margin = sum(leg['candidate'] - leg['baseline'] for leg in legs.values())
        completed.append(dict(pair=pair, blue=legs[1], red=legs[2], margin=margin))
    margins = [row['margin'] for row in completed]
    interval = None
    if len(margins) >= 8:
        rng = random.Random(2026)
        estimates = sorted(mean(rng.choices(margins, k=len(margins))) for _ in range(2000))
        interval = [estimates[50], estimates[1949]]
    return dict(pairs=completed, wins=sum(value > 0 for value in margins), draws=margins.count(0),
                losses=sum(value < 0 for value in margins), mean_margin=mean(margins) if margins else None,
                pending_pairs=len(pairs) - len(completed) - excluded, excluded_pairs=excluded, interval95=interval)
