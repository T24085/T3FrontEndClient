"""Select and score defensive tactics across local native match campaigns."""

from collections import defaultdict
import csv
import json
import math
from pathlib import Path
from statistics import mean

from batch import select
from learning_history import MOVEMENT, new_run_provenance, past_runs


DEFENSE_ROLES = ('Heavy on flag', 'Light defense', 'Medium defense')
HEAVY, LIGHT, MEDIUM = DEFENSE_ROLES
BASELINE = 'baseline'
EVIDENCE_VERSION = 1
TACTICAL_MODES = {'scrimmage', 'offdef', 'teams', 'defended', 'solo', 'explore', 'season'}
TACTICAL_SCENARIOS = {'role-scrimmage-v1', 'offense-defense-v1', 'seven-v-seven',
                      'ctf-roster-v1', 'capper-attack-v1', 'flank-exploration-v1', 'season-ctf-v1'}
LEGACY_SCENARIOS = {'grounded-defense', 'defender-learning-v1', 'juggernaut-body-block-v1',
                    'juggernaut-matched-tournament-v1', 'flag-pass-altitude-v1', 'flag-pass-pilot-v1',
                    'flag-pass-long-runup-v1', 'flag-pass-speed-sweep-v1'}

# Historical grounded-defense profile IDs are frozen in its saved checkpoints.
# Only the pursuit and combat-handoff settings transfer to a team match.
GROUNDED_PROFILES = (
    (5000, 2500, 2500, .45), (8500, 2500, 2500, .45), (6500, 1200, 2500, .45),
    (6500, 4000, 2500, .45), (6500, 2500, 4000, .45), (8500, 1600, 4000, .85),
    (8500, 3500, 4000, .15), (6500, 1600, 1200, .85),
)
TACTICS = {
    HEAVY: {BASELINE: dict(handoff=1600), **{
        f'handoff-{distance}': dict(handoff=distance)
        for _, _, distance, _ in GROUNDED_PROFILES
    }},
    LIGHT: {BASELINE: dict(trigger=6500, handoff=2400, lead=.5, incoming_lead=0, carrier_handoff=2000), **{
        f'pursuit-{index}': dict(trigger=trigger, handoff=light, lead=lead, incoming_lead=lead, carrier_handoff=light)
        for index, (trigger, light, _, lead) in enumerate(GROUNDED_PROFILES, 1)
    }},
    MEDIUM: {
        BASELINE: dict(depth=2200, handoff=2100, intercept=0),
        'close-support': dict(depth=1200, handoff=2700, intercept=3200),
        'forward-screen': dict(depth=3800, handoff=1600, intercept=5200),
    },
}


def lua_tactics(assignments, tactics=TACTICS):
    return '{' + ','.join(
        f'[{slot}]={{' + ','.join(f'{name}={value}' for name, value in tactics[role][profile].items()) + '}'
        for slot, (role, profile) in assignments.items()
    ) + '}'


def trace_frames(bots):
    frames = defaultdict(dict)
    for bot in bots:
        with Path(bot['trace']).open(newline='') as source:
            for row in csv.DictReader(source):
                if row['phase'] not in ('InProgress', 'flag_pickup', 'flag_lost', 'cap'):
                    continue
                if float(row['health']) <= 0:
                    continue
                position = tuple(float(row[f'{axis}_cm']) for axis in 'xyz')
                frames[float(row['seconds'])][bot['bot']] = (
                    position, float(row['home_flag_cm']), float(row['enemy_flag_cm']), row['carrying'] == '1')
    return frames


def confirmed_projectile_damage(match):
    damage = defaultdict(float)
    if match.get('combat_complete'):
        for event in match.get('combat', ()):
            if event['event'] == 'damage':
                damage[event['shooter']] += event['damage']
    return damage


def travel_reward_scale(jog_ratio):
    return max(.35,1-2.5*jog_ratio)


def match_evidence(match, assignments, frames=None):
    """Credit team outcomes plus role positioning under actual flag pressure."""
    bots = match['bots']
    frames = trace_frames(bots) if frames is None else frames
    combat_damage = confirmed_projectile_damage(match)
    evidence = []
    for team, opponent_score in ((1, match['red']), (2, match['blue'])):
        defenders = [bot for bot in bots if bot['team'] == team and bot['bot'] in assignments]
        opponents = [bot for bot in bots if bot['team'] != team]
        if not defenders or not opponents:
            continue
        pickups = sum(bot.get('pickups', 0) for bot in opponents)
        stopped = sum(event['team'] == 3 - team and event['event'] == 'carrier_down'
                      for event in match.get('events', ()))
        returns = sum(event['team'] == team and event['event'] == 'flag_returned' for event in match.get('events', ()))
        team_reward = (.5 / (1 + opponent_score) + .2 / (1 + pickups)
                       + .08 * min(1, stopped / max(1, pickups)) + .04 * min(1, returns / max(1, pickups)))
        exposures = 0
        coverage = defaultdict(int)
        for frame in frames.values():
            threats = [frame[bot['bot']] for bot in opponents if bot['bot'] in frame]
            carrier = next((row for row in threats if row[3]), None)
            incoming = [row for row in threats if 0 <= row[2] <= 6500]
            target = carrier or min(incoming, key=lambda row: row[2], default=None)
            if target is None:
                continue
            exposures += 1
            for bot in defenders:
                slot = bot['bot']
                observation = frame.get(slot)
                if observation is None:
                    continue
                role = assignments[slot][0]
                if role == HEAVY:
                    coverage[slot] += 0 <= observation[1] <= 1800
                else:
                    radius = (2200 if carrier else 2400) if role == LIGHT else 3000
                    coverage[slot] += math.dist(observation[0], target[0]) <= radius
        if exposures < 8:
            continue
        groups = defaultdict(list)
        for bot in defenders:
            slot = bot['bot']
            groups[assignments[slot]].append((coverage[slot] / exposures, combat_damage[slot],
                                              bot.get('open_travel_jog_ratio',0)))
        for (role, profile), rows in groups.items():
            positioning = mean(row[0] for row in rows)
            direct_damage = mean(row[1] for row in rows)
            jog_ratio = mean(row[2] for row in rows)
            evidence.append(dict(team=team, role=role, profile=profile, pressure_samples=exposures,
                                 opponent_captures=opponent_score, opponent_pickups=pickups,
                                 positioning=positioning, carriers_stopped=stopped, flag_returns=returns,
                                 confirmed_projectile_damage=direct_damage,
                                 open_travel_jog_ratio=jog_ratio,
                                 reward=min(1, team_reward + .3 * positioning + .08 * min(1, direct_damage / 125))
                                 * travel_reward_scale(jog_ratio)))
    return evidence


def legacy_evidence(checkpoint):
    for row in checkpoint.get('attempts', ()):
        metrics = row.get('defense')
        profile = row.get('defense_profile', 1)
        if not metrics or type(profile) is not int or not 1 <= profile <= len(GROUNDED_PROFILES):
            continue
        if row['seconds'] <= 0 or not metrics['hof_alive_seconds'] and not metrics['ld_alive_seconds']:
            continue
        _, _, handoff, _ = GROUNDED_PROFILES[profile - 1]
        outcome = .5 / (1 + row['capture']) + .2 / (1 + row['pickup'])
        home_coverage = min(1, metrics['hof_near_flag_seconds'] / row['seconds'])
        yield HEAVY, f'handoff-{handoff}', outcome + .3 * home_coverage
        chase_seconds = row['seconds'] - row['pickup_seconds']
        pursuit = (min(1, metrics['ld_near_carrier_seconds'] / chase_seconds)
                   if row['pickup'] and chase_seconds > 0 else .5)
        yield LIGHT, f'pursuit-{profile}', outcome + .3 * pursuit


def grounded_profile(history, rng):
    """Choose a grounded-drill profile using its Heavy and Light components."""
    scores = {}
    for index, (_, _, handoff, _) in enumerate(GROUNDED_PROFILES, 1):
        heavy = history[HEAVY][f'handoff-{handoff}']
        light = history[LIGHT][f'pursuit-{index}']
        available = [mean(rows) for rows in (heavy, light) if rows]
        weight = max(1, min(len(heavy), len(light)))
        scores[index] = [mean(available)] * weight if available else []
    return select(scores, rng, 1, score=float)


def assign_tactics(histories, roster, rng, index):
    teams = (2, 1) if index % 2 else (1, 2)
    choices = {}
    for role, history in histories.items():
        pool = history
        for team in teams:
            if (team, role) in roster:
                profile = select(pool, rng, BASELINE, score=float)
                choices[team, role] = profile
                pool = {key: rows for key, rows in history.items() if key != profile}
    return {slot: (role, choices[team, role]) for slot, (team, role) in enumerate(roster, 1)
            if (team, role) in choices}


def record_evidence(history, evidence):
    count = 0
    for row in evidence:
        scores = history.get(row['role'], {}).get(row['profile'])
        if scores is not None and 0 <= row['reward'] <= 1:
            scores.append(row['reward'])
            count += 1
    return count


class DefenseLearning:
    def __init__(self, output, map_id, matches):
        self.history = {role: {profile: [] for profile in profiles} for role, profiles in TACTICS.items()}
        self.sources = {}
        legacy = defaultdict(list)
        if map_id == 'HighOctane2026' and new_run_provenance(output) is None:
            for path in sorted(output.parent.parent.glob('Campaign-*/progress.json')):
                checkpoint = json.loads(path.read_bytes())
                spec = checkpoint.get('configuration', {})
                if spec.get('scenario') not in LEGACY_SCENARIOS or spec.get('map', map_id) != map_id:
                    continue
                self.load_drill(path.parent.name, checkpoint, legacy)
        for name, request, checkpoint in past_runs(output, None, map_id, require_runtime=True):
            if request['mode'] == 'defended' and checkpoint.get('configuration', {}).get('movement') == MOVEMENT:
                self.load_drill(name, checkpoint, legacy)
            elif request['mode'] in TACTICAL_MODES and checkpoint.get('scenario') in TACTICAL_SCENARIOS:
                self.load_matches(name, checkpoint['matches'])
        # One observation per tactic keeps smaller, isolated drills useful as
        # starting evidence while allowing live team matches to outweigh them.
        for (role, profile), scores in legacy.items():
            self.history[role][profile].append(mean(scores))
        self.load_matches(output.name, matches)

    def load_drill(self, name, checkpoint, legacy):
        count = 0
        for role, profile, reward in legacy_evidence(checkpoint):
            legacy[role, profile].append(reward)
            count += 1
        if count:
            self.sources[name] = count

    def load_matches(self, name, matches):
        count = 0
        for match in matches:
            if 'defense_evidence_version' in match:
                if match['defense_evidence_version'] == EVIDENCE_VERSION:
                    count += self.record(match['defense_evidence'])
                continue
            defaults = {bot['bot']: (bot['role'], BASELINE) for bot in match['bots']
                        if bot['role'] in TACTICS}
            if defaults:
                try:
                    count += self.record(match_evidence(match, defaults))
                except FileNotFoundError:
                    continue
        if count:
            self.sources[name] = count

    def record(self, evidence):
        return record_evidence(self.history, evidence)

    def assign(self, roster, rng, index):
        return assign_tactics(self.history, roster, rng, index)
