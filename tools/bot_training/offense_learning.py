"""Learn when Medium and Heavy Offense should push ahead of their cappers."""

from collections import defaultdict
import math
from statistics import mean

from defense_learning import (BASELINE, TACTICAL_MODES, TACTICAL_SCENARIOS,
                              assign_tactics, confirmed_projectile_damage, record_evidence, trace_frames, travel_reward_scale)
from learning_history import past_runs


MEDIUM_OFFENSE, HEAVY_OFFENSE = 'Medium offense', 'Heavy offense'
OFFENSE_ROLES = ('Capper', 'Capper', MEDIUM_OFFENSE, HEAVY_OFFENSE)
EVIDENCE_VERSION = 1
APPROACH_CM = 9000
STAND_CM = 3200

TACTICS = {
    MEDIUM_OFFENSE: {
        BASELINE: {},
        'early-flank': dict(launch=13500, stage=6100, strike=2200, flank=1800, handoff=2000),
        'timed-support': dict(launch=8200, stage=4500, strike=1600, flank=1050, handoff=2500),
        'late-sweep': dict(launch=5200, stage=3900, strike=1000, flank=1600, handoff=2100),
        'air-support': dict(launch=8200, stage=4500, strike=1600, flank=1050, handoff=2500,
                            jet_period=2.2, jet_pulse=.95),
    },
    HEAVY_OFFENSE: {
        BASELINE: {},
        'early-clear': dict(launch=15000, stage=6500, strike=1400, flank=-900, handoff=2400),
        'timed-clear': dict(launch=10000, stage=5200, strike=900, flank=-800, handoff=2700),
        'late-clear': dict(launch=6500, stage=4200, strike=600, flank=-500, handoff=2300),
        'air-clear': dict(launch=10000, stage=5200, strike=900, flank=-800, handoff=2700,
                          jet_period=2.6, jet_pulse=1.1),
        'base-raid': dict(launch=10500, stage=5200, strike=900, flank=-800, handoff=2000, raid=1),
    },
}


def cap_windows(match, frames, team, support):
    events = match.get('events', ())
    captures = [item for item in events if item['team'] == team and item['event'] == 'cap']
    pickups = [item for item in events if item['team'] == team and item['event'] == 'flag_pickup']
    touches = defaultdict(set)
    for clear in match.get('equipment_events', ()):
        if clear['team'] != 3-team:
            continue
        seconds = clear['seconds']
        clear_frame = frames.get(seconds, {})
        present = [slot for slot in support if slot in clear_frame
                   and math.dist(clear_frame[slot][0],clear['pos_cm']) <= 4000]
        for pickup in pickups:
            if not 0 < pickup['seconds']-seconds <= 12:
                continue
            for capture in captures:
                if pickup['bot'] == capture['bot'] and 0 < capture['seconds']-pickup['seconds'] <= 35:
                    intervening_loss = any(item['event'] in ('flag_lost','carrier_down') and item['bot'] == pickup['bot']
                        and pickup['seconds'] < item['seconds'] < capture['seconds'] for item in events)
                    if not intervening_loss:
                        for slot in present:
                            touches[slot].add((capture['bot'],capture['seconds']))
    return touches


def match_evidence(match, assignments, frames=None):
    """Score coordinated pressure, guard departures, and flag outcomes from team traces."""
    if not assignments:
        return []
    bots = match['bots']
    frames = trace_frames(bots) if frames is None else frames
    combat_damage = confirmed_projectile_damage(match)
    results = []
    for team, captures in ((1, match['blue']), (2, match['red'])):
        offense = [bot for bot in bots if bot['team'] == team and bot['bot'] in assignments]
        cappers = [bot for bot in bots if bot['team'] == team and bot['role'] == 'Capper']
        opponents = [bot for bot in bots if bot['team'] != team]
        if not offense or not cappers or not opponents:
            continue
        pickups = sum(bot.get('pickups', 0) for bot in cappers)
        team_reward = .25 * captures / (1 + captures) + .15 * pickups / (1 + pickups)
        equipment_down = sum(row['generators'] + row['turrets'] for row in match.get('base_equipment', ())
                             if row['team'] == 3 - team)
        cleared_windows = cap_windows(match,frames,team,{bot['bot'] for bot in offense})
        travel_jog = {bot['bot']:bot.get('open_travel_jog_ratio',0) for bot in offense}
        approaches = opportunities = 0
        timed = defaultdict(int)
        involved = defaultdict(int)
        departures = defaultdict(int)
        prior_guards, prior_pressure = set(), {}
        prior_time = None
        for seconds, frame in sorted(frames.items()):
            near_cappers = [frame[bot['bot']] for bot in cappers if bot['bot'] in frame
                            and 0 <= frame[bot['bot']][2] <= APPROACH_CM and not frame[bot['bot']][3]]
            if not near_cappers:
                prior_guards, prior_pressure, prior_time = set(), {}, None
                continue
            approaches += 1
            guards = {bot['bot']: frame[bot['bot']][0] for bot in opponents if bot['bot'] in frame
                      and 0 <= frame[bot['bot']][1] <= STAND_CM}
            opportunities += bool(guards)
            gone = prior_guards - guards.keys() if prior_time is not None and seconds - prior_time <= .5 else set()
            pressure = {}
            for bot in offense:
                slot = bot['bot']
                if slot in frame and 0 <= frame[slot][2] <= STAND_CM:
                    timed[slot] += 1
                    pressure[slot] = {guard for guard, position in guards.items()
                                      if math.dist(frame[slot][0], position) <= STAND_CM}
                    involved[slot] += bool(pressure[slot])
                departures[slot] += len(prior_pressure.get(slot, set()) & gone)
            prior_guards, prior_pressure, prior_time = guards.keys(), pressure, seconds
        if approaches < 8:
            continue
        groups = defaultdict(list)
        flight = {bot['bot']: bot.get('airborne_objective_advance_m', 0) for bot in offense}
        for bot in offense:
            groups[assignments[bot['bot']]].append(bot['bot'])
        for (role, profile), slots in groups.items():
            timing = mean(timed[slot] / approaches for slot in slots)
            pressure = mean(involved[slot] / max(1, opportunities) for slot in slots)
            cleared = mean(departures[slot] for slot in slots)
            flight_progress = mean(min(1, flight[slot] / 80) for slot in slots)
            direct_damage = mean(combat_damage[slot] for slot in slots)
            jog_ratio = mean(travel_jog[slot] for slot in slots)
            cap_support = mean(len(cleared_windows[slot]) for slot in slots)
            clear_reward = (.12*cap_support/(1+cap_support) if 'equipment_events' in match
                            else .06*equipment_down/(1+equipment_down))
            reward = min(1, team_reward + .25 * timing + .15 * pressure + .20 * cleared / (1 + cleared)
                         + .08 * flight_progress * timing + clear_reward
                         + .08 * min(1, direct_damage / 125))
            results.append(dict(team=team, role=role, profile=profile, reward=reward*travel_reward_scale(jog_ratio),
                                approach_samples=approaches, guarded_samples=opportunities, timing=timing,
                                guard_pressure=pressure, nearby_guard_departures=cleared,
                                airborne_progress=flight_progress,
                                confirmed_projectile_damage=direct_damage,
                                enemy_equipment_downed=equipment_down,
                                captures_after_nearby_clear=cap_support,
                                open_travel_jog_ratio=jog_ratio,
                                capper_pickups=pickups, team_captures=captures))
    return results


class OffenseLearning:
    def __init__(self, compatible_runs, matches):
        self.history = {role: {profile: [] for profile in profiles} for role, profiles in TACTICS.items()}
        self.sources = {}
        for name, previous in compatible_runs:
            self.load_matches(name, previous)
        self.load_matches('current-run', matches)

    def load_matches(self, name, matches):
        count = 0
        for match in matches:
            version = match.get('offense_evidence_version')
            if version == EVIDENCE_VERSION:
                count += self.record(match['offense_evidence'])
            elif version is None:
                assignments = {bot['bot']: (bot['role'], BASELINE) for bot in match['bots']
                               if bot['role'] in TACTICS}
                if assignments:
                    try:
                        count += self.record(match_evidence(match, assignments))
                    except FileNotFoundError:
                        continue
        if count:
            self.sources[name] = count

    @classmethod
    def for_run(cls, output, map_id, matches):
        compatible_runs = ((name, checkpoint['matches'])
                           for name, request, checkpoint in past_runs(output, None, map_id, require_runtime=True)
                           if request['mode'] in TACTICAL_MODES and checkpoint.get('scenario') in TACTICAL_SCENARIOS)
        return cls(compatible_runs, matches)

    def assign(self, roster, rng, index):
        return assign_tactics(self.history, roster, rng, index)

    def record(self, evidence):
        return record_evidence(self.history, evidence)
