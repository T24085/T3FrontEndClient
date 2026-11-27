"""Run an isolated training campaign from the local dashboard."""
import argparse
import csv
from dataclasses import asdict, replace
import json
import math
import msvcrt
import os
from pathlib import Path
from aim_learning import AIM_EVIDENCE_VERSION, assess_trial, benchmark_aim_report, calibration_report, trial_assignment
from statistics import median
import random
import re
import sys
import time

from batch import Campaign, FASTER_APPROACH, run, select
from defense_batch import DefenseCampaign, GroundedDefenseTrainer
from defense_learning import (DEFENSE_ROLES, EVIDENCE_VERSION, DefenseLearning, grounded_profile, legacy_evidence,
                              lua_tactics, match_evidence, trace_frames)
from learning_history import MOVEMENT, past_runs
from mirrored_benchmark import archived_opponents, freeze_tactics, pair_assignment, paired_results
import offense_learning
from practice import (HERE, MAP, MAX_TRAINING_BOTS, MISSING_GAME_CACHE, NativeMemoryBusy, TrainingPaused, TrainingStopped,
                      check_between_matches, start, training_wait)
from train import Trainer, fixed_training_teams, publish, read_ready, replace_once
from route_transfer import (candidate_keys, exploratory_routes, flank_assignments, flank_routes, guided_assignments, guided_evidence, route_evidence,
                            screening_candidates, trial_pickup_evidence)


TEAM_POLICIES = {
    'Balanced': offense_learning.OFFENSE_ROLES + DEFENSE_ROLES,
    'More cappers': ('Capper', 'Capper', 'Capper', 'Medium offense') + DEFENSE_ROLES,
    'More chasers': offense_learning.OFFENSE_ROLES + ('Heavy on flag', 'Light defense', 'Light defense'),
}
SCRIMMAGE_REINFORCEMENTS = ('Capper', 'Light defense', 'Medium offense', 'Medium defense', 'Heavy offense')
ASSET_SLOTS = {
    'Capper': 'roles[1]', 'Offense': 'data', 'Heavy defense': 'roles[2]', 'Chaser': 'roles[3]',
    'Medium offense': 'data', 'Heavy offense': '(roles[4] or roles[2])', 'Heavy on flag': 'roles[2]',
    'Light defense': 'roles[3]', 'Medium defense': '(roles[5] or data)',
}

MAX_TEAM_BOTS = MAX_TRAINING_BOTS // 2


def team_roles(policy, size):
    roles = TEAM_POLICIES[policy]
    if size >= len(roles):
        return tuple(roles[index % len(roles)] for index in range(size))
    # Keep a capper and defense in the balanced lineup as it scales down.
    order = {'Balanced': (0, 4, 2, 6, 1, 3, 5),
             'More cappers': (0, 1, 4, 2, 3, 5, 6),
             'More chasers': (6, 0, 5, 2, 4, 1, 3)}[policy]
    return tuple(roles[index] for index in order[:size])


def competitive_roles(size, mode):
    if mode == 'season' or size < 7:
        return team_roles('Balanced', size)
    return offense_learning.OFFENSE_ROLES + DEFENSE_ROLES + SCRIMMAGE_REINFORCEMENTS[:size - 7]


class NoBrakingTrainer(Trainer):
    measure_approach = True
    reuse_trials = False

    def instrument(self, text, out):
        reuse = (f'verify_reuse=true,reuse_script={json.dumps((HERE/"verify_trial_reset.lua").as_posix())},'
                 if self.reuse_trials else '')
        return replace_once(super().instrument(text, out), '  path=',
                            '  no_braking=true,long_runups=true,speed_sweep=true,approach_reward=true,'+reuse+'path=')


class NoBrakingDefenseTrainer(GroundedDefenseTrainer, NoBrakingTrainer):
    def instrument(self, text, out):
        return replace_once(super().instrument(text, out), 'no_braking=true,',
                            'no_braking=true,adaptive_defense=true,')


class FlyThroughCampaign:
    trials_per_match = 1
    routes = {1: (9500, 4, 'Right 95 m Â· low lift'), -1: (9500, 4, 'Left 95 m Â· low lift'),
              2: (8500, 4, 'Right 85 m Â· low lift'), -2: (12500, 5, 'Left 125 m Â· high lift')}

    def policy_configuration(self):
        self.baseline = replace(FASTER_APPROACH, flank=-2)
        self.policies = tuple(replace(self.baseline, flank=flank) for flank in self.routes)
        return dict(super().policy_configuration(), movement=MOVEMENT,
                    route_settings={str(key): list(value) for key, value in self.routes.items()})

    def load_history(self, mode):
        keys = ('movement', 'route_settings', 'policies', 'seconds', 'scenario')
        map_id = getattr(self, 'map_id', MAP)
        matching_runs = [(name, report) for name, _, report in past_runs(self.root, mode, map_id)
                         if 'configuration' in report
                         and all(report['configuration'].get(key) == self.spec.get(key) for key in keys)]
        self.prior_trials = tuple(
            row for _, report in matching_runs
            for row in report['attempts'] if not row['held_out'] and row.get('pass_runup_cm', 0) > 0
        )
        candidates = []
        policy_by_route = {}
        for policy in self.policies:
            runup, guidance, name = self.routes[policy.flank]
            candidates.append(dict(approach_route=name, policy=asdict(policy), pass_runup_cm=runup, guidance=guidance))
            policy_by_route[name] = policy
        exact_sources = {name for name, _ in matching_runs}
        self.route_priors = {policy: [] for policy in self.policies}
        for row in route_evidence(self.root, map_id, candidates):
            if row['source'] not in exact_sources:
                self.route_priors[policy_by_route[row['route']]].append(row)

    def learning_history(self):
        return getattr(self, 'prior_trials', ())

    def report_fields(self):
        return dict(super().report_fields(), carried_forward=len(self.learning_history())
                    + sum(map(len, getattr(self, 'route_priors', {}).values())))

    def select_policy(self, history, rng):
        from paired_flag_screen import screening_score
        prior = getattr(self, 'route_priors', {})
        pool = {policy: [*(trial_pickup_evidence(row) for row in rows), *prior.get(policy, ())]
                for policy, rows in history.items()}
        return select(pool, rng, self.baseline, screening_score)

    def play_attempt(self, attempt, policy, spawn, offset, evaluating):
        runup, guidance, name = self.routes[policy.flank]
        return dict(attempt(policy, spawn, offset, evaluating, defense_profile=0,
                            pass_runup_cm=runup, pass_guidance=guidance), approach_route=name)


class FreshSolo(FlyThroughCampaign, Campaign):
    def make_trainer(self):
        trainer = NoBrakingTrainer(0, self.seconds, self.seed, False, batch=self.play)
        trainer.reuse_trials = self.trials_per_match > 1
        return trainer


class FreshDefense(FlyThroughCampaign, DefenseCampaign):
    def make_trainer(self):
        trainer = NoBrakingDefenseTrainer(0, self.seconds, self.seed, False, batch=self.play)
        trainer.reuse_trials = self.trials_per_match > 1
        return trainer

    def load_history(self, mode):
        super().load_history(mode)
        self.defense_learning = DefenseLearning(self.root, self.map_id, [])
        self.record_defense(self.rows)

    def record_defense(self, rows):
        for role, profile, reward in legacy_evidence({'attempts': rows}):
            self.defense_learning.history[role][profile].append(reward)

    def play_attempt(self, attempt, policy, spawn, offset, evaluating):
        rng = random.Random(f'{self.seed}:defense:{len(self.rows)}')
        profile = 1 if evaluating else grounded_profile(self.defense_learning.history, rng)
        runup, guidance, name = self.routes[policy.flank]
        row = dict(attempt(policy, spawn, offset, evaluating, defense_profile=profile,
                           pass_runup_cm=runup, pass_guidance=guidance), approach_route=name,
                   defense_profile=profile)
        self.record_defense([row])
        return row


def team_bot_metrics(samples):
    observed = [row for row in samples if not row['phase'].startswith('death') and
                (not row.get('health') or float(row['health']) > 0)]
    speeds = [.036 * math.hypot(float(row['vx_cm_s']), float(row['vy_cm_s'])) for row in observed]
    pairs = [(first, second, min(.35, float(second['seconds']) - float(first['seconds'])))
             for first, second in zip(observed, observed[1:])
             if 0 < float(second['seconds']) - float(first['seconds']) <= .5]
    data = dict(peak_kmh=max(speeds, default=None), median_kmh=median(speeds) if speeds else None,
                samples=len(observed), flag_samples=sum(row['carrying'] == '1' for row in observed),
                ski_seconds=sum(dt for row, _, dt in pairs if row['ski'] == '1'),
                jet_seconds=sum(dt for row, _, dt in pairs if row['jet'] == '1'),
                carry_seconds=sum(dt for row, _, dt in pairs if row['carrying'] == '1'))
    if samples and samples[0].get('health') is not None:
        pickups = [speed for row, speed in zip(observed, speeds) if row['phase'] == 'flag_pickup']
        data.update(pickups=len(pickups), fast_pickups=sum(speed >= 100 for speed in pickups),
                    median_pickup_kmh=median(pickups) if pickups else None,
                    releases=sum(row['phase'] == 'flag_lost' for row in samples),
                    deaths=sum(row['phase'].startswith('death') for row in samples),
                    captures=sum(row['phase'] == 'cap' for row in samples),
                    health_lost=sum(max(0, float(row['health']) - float(next_row['health']))
                                    for row, next_row, _ in pairs),
                    home_flag_seconds=sum(dt for row, _, dt in pairs if 0 <= float(row['home_flag_cm']) <= 3000),
                    enemy_flag_seconds=sum(dt for row, _, dt in pairs if 0 <= float(row['enemy_flag_cm']) <= 3000))
    if observed and 'grounded' in observed[0]:
        air = [(row, next_row, dt) for row, next_row, dt in pairs if row['grounded'] == '0']
        data['airborne_seconds'] = sum(dt for _, _, dt in air)
        moving = [(row,dt) for row,_,dt in pairs
                  if .036*math.hypot(float(row['vx_cm_s']),float(row['vy_cm_s'])) >= 3]
        jog = [(row,dt) for row,dt in moving if row['grounded'] == '1' and row['ski'] == row['jet'] == '0']
        data['ground_jog_seconds'] = sum(dt for _,dt in jog)
        open_travel = sum(dt for row,dt in moving if row.get('open_travel') == '1')
        if open_travel:
            open_jog = sum(dt for row,dt in jog if row.get('open_travel') == '1')
            data.update(open_travel_seconds=round(open_travel,2),open_travel_jog_ratio=round(open_jog/open_travel,4))
        advance = 0
        for row, next_row, _ in air:
            field = 'home_flag_cm' if row['carrying'] == '1' else 'enemy_flag_cm'
            before, after = float(row[field]), float(next_row[field])
            if before >= 0 and after >= 0 and row['carrying'] == next_row['carrying']:
                advance += (before - after) / 100
        data['airborne_objective_advance_m'] = max(0, advance)
    return data


class TeamTrainer(Trainer):
    match_script = 'team_match.lua'
    record_combat = True
    template_bot_count = 1
    waves_per_launch = 1
    verify_start = False
    strict_movement = False
    adaptive_movement = False

    def __init__(self, blue_roles, red_roles, seconds):
        super().__init__(0, seconds, 0, False)
        self.began = time.monotonic()
        self.roster = tuple((1, role) for role in blue_roles) + tuple((2, role) for role in red_roles)
        self.counts = len(blue_roles), len(red_roles)
        self.largest_team = max(self.counts)
        self.bot_count = len(self.roster)
        self.match = None
        self.result = None
        self.guided = {}
        self.defense_tactics = {}
        self.offense_tactics = {}
        self.capture_limit = None
        self.base_equipment = False
        self.aim_boosts = {}
        self.flight_transfer = {}
        self.human_reference = {}
        self.pursuit = {}
        self.adaptive_team = None
        self.spawn_cohort = None

    def instrument(self, text, out):
        text = super().instrument(text, out)
        text = replace_once(text, (HERE/'native_trials.lua').as_posix(), (HERE/self.match_script).as_posix())
        blue, red = self.counts
        tactical_roles = set(DEFENSE_ROLES) | offense_learning.TACTICS.keys()
        tactical = any(role in tactical_roles for _, role in self.roster)
        roles = '{' + ','.join(json.dumps(role) for _, role in self.roster) + '}' if tactical or self.strict_movement else '{}'
        tactics = f'defense_tactics={lua_tactics(self.defense_tactics)},' if self.defense_tactics else ''
        if self.offense_tactics:
            tactics += f'offense_tactics={lua_tactics(self.offense_tactics, offense_learning.TACTICS)},'
        if tactics or self.strict_movement:
            tactics += f'role_movement_script={json.dumps((HERE/"role_movement.lua").as_posix())},'
        if self.strict_movement:
            tactics += 'strict_movement=true,'
        if self.adaptive_movement:
            tactics += f'adaptive_movement=true,field_tactics_script={json.dumps((HERE/"field_tactics.lua").as_posix())},'
            if self.flight_transfer:
                profiles = ','.join(f'{course}={{pulse={profile["pulse"]},period={profile["period"]}}}'
                                    for course, profile in self.flight_transfer.items())
                tactics += f'flight_transfer={{{profiles}}},'
            if self.human_reference:
                tactics += f'jet_reserve={self.human_reference["jet_reserve"]},'
            if self.pursuit:
                tactics += f'pursuit_lead={self.pursuit["lead"]},'
            if self.adaptive_team:
                tactics += f'adaptive_team={self.adaptive_team},'
        if self.live_player:
            tactics += 'live_player=true,'
        if self.capture_limit:
            tactics += f'capture_limit={self.capture_limit},'
        if self.base_equipment:
            tactics += 'base_equipment=true,'
        if self.record_combat and blue and red and not self.live_player:
            tactics += (f'combat_script={json.dumps((HERE/"combat_telemetry.lua").as_posix())},'
                        f'combat_effects_script={json.dumps((HERE/"combat_effects.lua").as_posix())},')
            if self.aim_boosts:
                tactics += 'aim_boosts={' + ','.join(f'[{team}]={level}' for team, level in self.aim_boosts.items()) + '},'
        text = replace_once(text, '  path=',
                            f'  seconds={self.seconds},blue={blue},red={red},roles={roles},{tactics}path=')
        if self.guided:
            assignments = []
            for index, plan in self.guided.items():
                policy = plan['policy']
                fields = ','.join(f'{name}={policy[name]}' for name in ('pulse', 'period', 'ski', 'turn', 'flank'))
                layout = f'layout={json.dumps(plan["layout"])},' if plan.get('layout') else ''
                assignments.append(f'[{index}]={{name={json.dumps(plan["approach_route"])},{layout}'
                                   f'runup={plan["pass_runup_cm"]},guidance={plan["guidance"]},{fields}}}')
            guide_script = json.dumps((HERE/'team_capper.lua').as_posix())
            guided = '{' + ','.join(assignments) + '}'
            text = replace_once(text, '  seconds=',
                                f'  guide_script={guide_script},guided={guided},approach_reward=true,seconds=')
        text = replace_once(text, 'bots=1,capture_point=', f'bots={self.bot_count},capture_point=')
        text = fixed_training_teams(text, (team for team, _ in self.roster))
        roster = ','.join(ASSET_SLOTS[role] for _, role in self.roster)
        training_roles = '{[4]=true,[5]=true}' if tactical else '{}'
        text = replace_once(text, '   engine_valid=engine_valid}', f'   engine_valid=engine_valid,roster={{{roster}}}}}')
        if self.spawn_cohort:
            holdout, round_number = self.spawn_cohort
            cohort = json.dumps((HERE/'spawn_cohort.lua').as_posix())
            text = replace_once(text, '  for _,team in ipairs(teams) do\n   assert(#starts[team]>0',
                f'  assert(loadfile({cohort}))()(starts,{str(holdout).lower()},{round_number})\n'
                '  for _,team in ipairs(teams) do\n   assert(#starts[team]>0')
        text = replace_once(text, '  local data_path=', f"""
  local roles=assert(loadfile({json.dumps((HERE/'role_assets.lua').as_posix())}))()(valid,report,{training_roles})
  local data_path=""")
        if tactical:
            heavy_check = ''
            if any(role == 'Heavy on flag' for _, role in self.roster):
                heavy_check = f"assert(loadfile({json.dumps((HERE/'juggernaut.lua').as_posix())}))()(roles[2],valid,report,signature)"
            text = replace_once(text, '  local dependencies={}', f"""
  if not roles[4] then report('BOT_ROLE_COMPOSED|heavy_offense|native_heavy_loadout|training_positioning') end
  if not roles[5] then report('BOT_ROLE_COMPOSED|medium_defense|native_medium_loadout|training_positioning') end
  {heavy_check}
  local dependencies={{}}""")
        text = replace_once(text, 'SpawnBotFromDataWithTeamId(gm,state.data,team',
                            'SpawnBotFromDataWithTeamId(gm,state.roster[#entries+1],team')
        text = replace_once(text, "   assert(owned(bot,gm:GetWorld()),'match_rules_bot_world_mismatch')",
                            '   if not owned(bot,gm:GetWorld()) then return end')
        text = replace_once(text, 'deadline=os.time()+45', 'deadline=os.time()+120')
        text = replace_once(text, """   local entry=assert(entries[1])
   assert(#entries==1 and entry.team==1 and entry.pawn and entry.controller,'training_single_blue_bot')
   training_started=true
   local ok, why=pcall(train,gm,gs,entry.pawn,entry.controller)""", """   training_started=true
   local ok, why=pcall(train,gm,gs,entries)""")
        if self.waves_per_launch > 1 or self.verify_start:
            from team_waves import instrument
            text = instrument(text, self.match_script)
        return text

    def run(self, out, process):
        self.match = out
        if getattr(self, 'save_match', None):
            from team_waves import run_waves
            return run_waves(self, out, process)
        self.read_match(out, process)
        if getattr(self, 'save_match', None):
            self.save_match(self)

    def read_match(self, out, process, wave=1):
        from team_waves import evidence_path, ready_receipt
        file = lambda name: evidence_path(out, wave, name)
        ready_receipt(self, out, process, wave)
        blue_count, red_count = self.counts
        marker = f'BOT_TEAM_READY|{blue_count}|{red_count}'
        self.wait(out, process, lambda log: marker in log.splitlines(), 540)
        print(f'Native {blue_count}v{red_count} roster ready.', flush=True)
        raw = self.wait(out, process, lambda _: read_ready(file('team-result.csv')), self.seconds*4+100)
        if self.aim_boosts:
            expected = f'{wave},{self.aim_boosts.get(1,0)},{self.aim_boosts.get(2,0)}\n'
            if read_ready(file('team-aim-plan.csv')) != expected:
                raise RuntimeError('training_reuse_unverified|aim_profile_receipt')
        elapsed, blue, red, state = raw.split(',')
        bots = []
        for index, (team, role) in enumerate(self.roster, 1):
            trace = file(f'team-bot-{index}-trace.csv')
            with trace.open(newline='') as source:
                samples = list(csv.DictReader(source))
            bots.append(dict(bot=index, team=team, role=role, trace=str(trace), **team_bot_metrics(samples)))
        with file('team-score.csv').open(newline='') as source:
            scores = [dict(seconds=float(row['seconds']), blue=int(row['blue']), red=int(row['red']))
                      for row in csv.DictReader(source)]
        guided_routes = []
        if self.guided:
            with file('team-guided.csv').open(newline='') as source:
                for row in csv.DictReader(source):
                    bot = int(row['bot'])
                    plan = self.guided[bot]
                    guided_routes.append(dict(bot=bot, team=self.roster[bot-1][0], route=plan['approach_route'], policy=plan['policy'],
                                              layout=plan.get('layout'),
                                              runup_cm=plan['pass_runup_cm'], guidance=plan['guidance'],
                                              outcome=row['outcome'], pickup_kmh=float(row['pickup_kmh']),
                                              homeward_kmh=float(row['homeward_kmh']), skiing=row['skiing'] == '1'))
                    if row.get('approach_entry_kmh') and row.get('approach_peak_kmh'):
                        guided_routes[-1].update(approach_entry_kmh=float(row['approach_entry_kmh']),
                                                 approach_peak_kmh=float(row['approach_peak_kmh']))
                    if row.get('pass_gap_m') and row.get('pass_speed_kmh'):
                        guided_routes[-1].update(pass_gap_m=float(row['pass_gap_m']),
                                                 pass_speed_kmh=float(row['pass_speed_kmh']))
                    if row.get('escape_seconds'):
                        guided_routes[-1]['escape_seconds'] = float(row['escape_seconds'])
                    if row.get('failure'):
                        guided_routes[-1]['failure'] = row['failure']
        self.result = dict(seconds=float(elapsed), blue=int(blue), red=int(red), state=state, bots=bots,
                           score_timeline=scores, guided_routes=guided_routes)
        if self.adaptive_team and self.spawn_cohort:
            from team_waves import validate_reset
            validate_reset(out,wave,len(self.roster))
            with (out/f'team-reset-{wave}.csv').open(newline='') as source:
                self.result['spawn_fingerprint'] = [[round(float(row[f'{axis}_cm'])/10) for axis in 'xyz']
                                                     for row in csv.DictReader(source)]
        with file('team-events.csv').open(newline='') as source:
            self.result['events'] = [dict(seconds=float(row['seconds']), event=row['event'],
                                          team=int(row['team']), bot=int(row['bot']) or None)
                                     for row in csv.DictReader(source)]
        event_status = file('team-events-status.csv')
        if event_status.is_file():
            self.result['flag_returns_observed'] = event_status.read_text().strip() == 'returns_observed'
        combat = file('team-combat.csv')
        if combat.is_file():
            with combat.open(newline='') as source:
                observations = []
                for row in csv.DictReader(source):
                    event = row['event']
                    observed = dict(seconds=float(row['seconds']), shot=int(row['shot']), projectile=row['projectile'],
                                    shooter=int(row['shooter']), shooter_team=int(row['shooter_team']), event=event)
                    if row.get('shooter_airborne') in ('0','1'):
                        observed['shooter_airborne'] = row['shooter_airborne']=='1'
                    if event in ('damage','contact') or row.get('aim_angle_deg'):
                        observed.update(target=int(row['target']), target_team=int(row['target_team']),
                                        range_m=float(row['range_m']), airborne=row['airborne']=='1')
                    if event in ('damage','contact'):
                        observed['source'] = row.get('source') or 'contact'
                    if event == 'damage':
                        observed['damage'] = float(row['damage'])
                    if row.get('aim_angle_deg'):
                        observed['aim_angle_deg'] = float(row['aim_angle_deg'])
                    observations.append(observed)
            self.result['combat'] = observations
            self.result['combat_complete'] = file('team-combat-status.csv').read_text().strip() == 'complete'
        aim = file('team-aim.csv')
        if aim.is_file():
            with aim.open(newline='') as source:
                self.result['aim'] = [{field: int(value) for field, value in row.items()}
                                      for row in csv.DictReader(source)]
        if self.defense_tactics or self.offense_tactics:
            self.result['role_travel_fallback_enabled'] = True
        if self.offense_tactics:
            with file('team-offense-commands.csv').open(newline='') as source:
                self.result['offense_commands'] = [
                    {name: int(value) for name, value in row.items()} for row in csv.DictReader(source)]
        if self.base_equipment:
            with file('team-base-equipment.csv').open(newline='') as source:
                equipment = [{name: int(value) for name, value in row.items()} for row in csv.DictReader(source)]
            self.result['base_equipment'] = equipment
            self.result['base_equipment_changed'] = any(row['changed'] for row in equipment)
            receipt = file('team-equipment-events.csv')
            if receipt.is_file():
                with receipt.open(newline='') as source:
                    self.result['equipment_events'] = [dict(seconds=float(row['seconds']),kind=row['kind'],
                        team=int(row['team']),pos_cm=[float(row[key]) for key in ('x_cm','y_cm','z_cm')])
                        for row in csv.DictReader(source)]


def flank_score(row):
    from paired_flag_screen import screening_score
    if row['contact']:
        homeward = row.get('homeward_kmh') or 0
        escape = row.get('escape_seconds')
        return (screening_score(row) + min(1, max(0, homeward) / 100) + bool(row.get('captured'))
                + (.3 / (1 + escape / 3) if escape is not None else 0))
    gap = row.get('pass_gap_m')
    if gap is None:
        return 0
    return .25 * max(0, 1 - gap / 15) * min(1, (row.get('pass_speed_kmh') or 0) / 100)


def team_run(config, output, matches, seconds, seed, size=7, attack=None, mode='teams', waves_per_launch=1,
             evaluation=False, aim_calibration=False):
    output.mkdir(parents=True, exist_ok=True)
    path = output/'progress.json'
    scenario = 'seven-v-seven' if attack is None and size == 7 else 'ctf-roster-v1' if attack is None else 'capper-attack-v1'
    tactical = mode in ('scrimmage', 'offdef', 'season')
    if tactical:
        scenario = 'role-scrimmage-v1' if mode == 'scrimmage' else 'offense-defense-v1'
    if mode == 'explore':
        scenario = 'flank-exploration-v1'
    elif mode == 'season':
        scenario = 'season-ctf-v1'
    if evaluation:
        if mode not in ('scrimmage', 'season') or matches < 2 or matches % 2:
            raise ValueError('An evaluation needs two matches per mirrored pair.')
        scenario = 'mirrored-role-evaluation-v1'
    if aim_calibration:
        if evaluation or mode not in ('scrimmage','season') or matches < 2 or matches % 2:
            raise ValueError('Aim calibration needs two matches per mirrored pair in a full CTF roster.')
        scenario = 'mirrored-aim-calibration-v1'
    counts = (4, 3) if mode == 'offdef' else (size, size) if attack is None else attack
    map_id = config.get('training_map', MAP)
    report = dict(scenario=scenario, map=map_id, target=matches, seconds=seconds, seed=seed, matches=[],
                  roster=list(counts))
    if not (evaluation or aim_calibration):
        report['movement_policy'] = 'field-ski-jet-v1'
    elif evaluation:
        report['field_benchmark'] = True
    if not aim_calibration and not path.exists():
        from flight_training import qualified_flight_transfer
        from field_duel import qualified_pursuit_lead
        from human_reference import load_reference
        report['flight_transfer'] = qualified_flight_transfer(output,map_id)
        report['human_reference'] = load_reference(config,map_id)
        report['pursuit'] = qualified_pursuit_lead(output,map_id)
    if not evaluation and mode in ('solo', 'defended', 'explore', 'offdef'):
        report['mirror_drills'] = True
    if mode == 'teams':
        report['mirror_lineups'] = True
    if path.exists():
        prior = json.loads(path.read_bytes())
        if (any(prior[key] != report[key] for key in ('scenario','target','seconds','seed'))
                or prior.get('roster', [7, 7]) != report['roster'] or prior.get('map', MAP) != map_id):
            raise ValueError('Use the same settings to resume this run.')
        report = prior
    attack_policies = {
        'Balanced defense': ('Heavy on flag', 'Light defense', 'Medium defense'),
        'Heavy defense': ('Heavy on flag',),
        'Light chasers': ('Light defense',),
    }
    policies = TEAM_POLICIES if attack is None else attack_policies
    prior_matches = [
        dict(row, cross_roster=previous.get('roster', [7, 7]) != list(counts))
        for _, _, previous in past_runs(output, mode, map_id, require_runtime=True)
        if previous.get('scenario') == report['scenario'] and previous.get('seconds') == seconds
        and previous.get('movement_policy') == report.get('movement_policy')
        and (attack is not None or previous.get('roster', [7, 7]) == list(counts))
        for row in previous['matches'] if row['policy'] in policies and 'defense_tactics' in row
    ]
    from paired_flag_screen import CAP_SPEED_OBJECTIVE, screening_score
    candidate_source = output.parent.parent/'Campaign-FlagPassSpeed500/progress.json'
    if mode == 'explore':
        candidates = list(flank_routes())
    else:
        candidates = screening_candidates(output.parent.parent) if candidate_source.is_file() else []
        candidates.extend(exploratory_routes())
        candidates.extend(flank_routes())
    route_rows = route_evidence(output, map_id, candidates) if candidates else []
    report['carried_forward'] = len(prior_matches) + len(route_rows)
    report['learning_sources'] = dict(lineups=len(prior_matches), routes=len(route_rows),
                                      batches=sorted({row['source'] for row in route_rows}))
    defense = DefenseLearning(output, map_id, report['matches']) if counts[1] else None
    offense = offense_learning.OffenseLearning.for_run(output, map_id, report['matches']) if attack is None else None
    if defense:
        report['learning_sources']['defense'] = defense.sources
    if offense:
        report['learning_sources']['offense'] = offense.sources
    route_keys = candidate_keys(candidates)
    route_rows.extend(guided_evidence(report['matches'], output.name, route_keys))
    defense_setups = tuple(attack_policies) if mode == 'defended' and counts[1] else ()
    ctf_rules = mode == 'season' or config.get('paired_ctf_rules') is True
    paired_roles = competitive_roles(size, 'season' if ctf_rules else mode)
    if evaluation or aim_calibration:
        report['aim_roster'] = list(paired_roles)
        if 'frozen_tactics' not in report:
            report['frozen_tactics'] = freeze_tactics(paired_roles, defense, offense)
        if report.get('field_benchmark') and 'opponents' not in report:
            batches = [(source,saved['matches']) for source, _, saved in past_runs(output,None,map_id,require_runtime=True)
                       if saved.get('matches') and saved.get('roster') == list(counts)]
            report['opponents'] = archived_opponents(batches,report['frozen_tactics'],defense,offense)
    aim_batches = [
        saved['matches'] for _, request, saved in past_runs(output,None,map_id,require_runtime=True,aim_calibration=True)
        if saved.get('scenario')=='mirrored-aim-calibration-v1' and saved.get('seconds')==seconds
        and saved.get('roster')==list(counts)
        and (saved.get('aim_roster') == list(paired_roles)
             or ('aim_roster' not in saved and request.get('mode') == mode))
        and saved.get('frozen_tactics', {}).get('candidate')==report['frozen_tactics']['candidate']
    ] if evaluation or aim_calibration else []
    if evaluation and 'aim_benchmark_profile' not in report:
        report['aim_benchmark_profile'] = 0 if report['matches'] else calibration_report(aim_batches)['selected']
    if aim_calibration:
        report['aim_comparison'] = calibration_report([*aim_batches, report['matches']])
    publish(path, json.dumps(report, indent=2)+'\n')
    def prepare_match():
        index = len(report['matches'])
        mirrored = report.get('mirror_drills') or report.get('mirror_lineups')
        second_leg = mirrored and index % 2 == 1
        lead_with_blue = index // 2 % 2 == 0
        history = {policy: [] for policy in policies}
        for row in (*prior_matches, *report['matches']):
            if row['policy'] in history and 'defense_tactics' in row:
                history[row['policy']].append(row)
        rng = random.Random(f'{seed}:{len(prior_matches)+index}')
        if evaluation or aim_calibration:
            policy = 'Frozen role tactics'
            trainer = TeamTrainer(paired_roles, paired_roles, seconds)
            if ctf_rules:
                trainer.capture_limit = 5
            frozen = report['frozen_tactics']
            if report.get('field_benchmark'):
                opponent = report['opponents'][(index//2)%len(report['opponents'])]
                frozen = frozen | {'baseline': opponent['tactics']}
                trainer.benchmark_opponent = opponent['label']
                trainer.spawn_cohort = (True, index//2+1)
            pair, team, defensive, offensive = pair_assignment(frozen, trainer.roster, index, defense, offense)
            if aim_calibration:
                pair, team, level = trial_assignment(index)
                same_tactics = report['frozen_tactics'] | {'baseline': report['frozen_tactics']['candidate']}
                _, _, defensive, offensive = pair_assignment(same_tactics, trainer.roster, index, defense, offense)
                trainer.aim_pair, trainer.aim_level, trainer.candidate_team = pair, level, team
                trainer.aim_boosts = {team: level}
            else:
                trainer.benchmark_pair, trainer.candidate_team = pair, team
                trainer.aim_boosts = {team: report.get('aim_benchmark_profile', 0)}
                if report.get('field_benchmark'):
                    trainer.adaptive_team = team
            trainer.defense_tactics, trainer.offense_tactics = defensive, offensive
            candidate_on_blue = team == 1
            candidate, baseline = ('Aim profile', 'Native aim') if aim_calibration else (
                'Candidate tactics', getattr(trainer,'benchmark_opponent','Baseline tactics'))
            blue, red = (candidate, baseline) if candidate_on_blue else (baseline, candidate)
        elif second_leg:
            first = report['pending_mirror']
            policy, red, blue, first_candidate_on_blue = first['labels']
            candidate_on_blue = not first_candidate_on_blue
            first_blue, first_red = first['counts']
            roles = [role for _, role in first['roster']]
            trainer = TeamTrainer(roles[first_blue:], roles[:first_blue], seconds)
            def swapped(assignments):
                return {(slot + first_red if slot <= first_blue else slot - first_blue): plan
                        for key, plan in assignments.items() if (slot := int(key)) > 0}
            trainer.guided = swapped(first['routes'])
            # JSON restores tactic pairs as lists, but evidence groups use them as keys.
            trainer.defense_tactics = {slot: tuple(plan) for slot, plan in swapped(first['defense']).items()}
            trainer.offense_tactics = {slot: tuple(plan) for slot, plan in swapped(first['offense']).items()}
        elif mode == 'explore':
            policy = 'Flank exploration'
            candidate_on_blue = lead_with_blue if mirrored else index % 2 == 0 or not attack[1]
            opponent = 'Defenders' if attack[1] else 'No defenders'
            cappers = ('Capper',) * attack[0]
            defenders = tuple(DEFENSE_ROLES[i % len(DEFENSE_ROLES)] for i in range(attack[1]))
            blue_roles, red_roles = (cappers, defenders) if candidate_on_blue else (defenders, cappers)
            blue, red = ('Flank cappers', opponent) if candidate_on_blue else (opponent, 'Flank cappers')
            trainer = TeamTrainer(blue_roles, red_roles, seconds)
        elif tactical:
            policy, candidate_on_blue = 'Role roster', True
            if mode == 'offdef':
                candidate_on_blue = lead_with_blue if mirrored else True
                blue, red = ('Offense', 'Defense') if candidate_on_blue else ('Defense', 'Offense')
                roster = (offense_learning.OFFENSE_ROLES, DEFENSE_ROLES)
                trainer = TeamTrainer(*(roster if candidate_on_blue else roster[::-1]), seconds)
            elif mode == 'season':
                blue = red = 'Balanced offense and defense'
                roster = competitive_roles(size, mode)
                trainer = TeamTrainer(roster, roster, seconds)
                trainer.capture_limit = 5
            else:
                blue = red = 'Competitive roster'
                roster = competitive_roles(size, mode)
                trainer = TeamTrainer(roster, roster, seconds)
        elif attack is None:
            policy = select(history, rng, 'Balanced', lambda row: row['margin'])
            candidate_on_blue = lead_with_blue if mirrored else len(history[policy]) % 2 == 0
            blue, red = (policy, 'Balanced') if candidate_on_blue else ('Balanced', policy)
            trainer = TeamTrainer(team_roles(blue, size), team_roles(red, size), seconds)
        else:
            blue_count, red_count = attack
            if mirrored and defense_setups:
                pair = index // 2
                block = pair // len(defense_setups)
                policy = defense_setups[(pair + block) % len(defense_setups)]
            else:
                policy = select(history, rng, 'Balanced defense',
                                lambda row: row['margin'] * (.5 if row.get('cross_roster') else 1)) if red_count else 'Balanced defense'
            roles = attack_policies[policy]
            attack_on_blue = lead_with_blue if mirrored else True
            candidate_on_blue = not attack_on_blue
            opponent = policy if red_count else 'No defenders'
            blue, red = ('Cappers', opponent) if attack_on_blue else (opponent, 'Cappers')
            roster = ('Capper',) * blue_count, tuple(roles[i % len(roles)] for i in range(red_count))
            trainer = TeamTrainer(*(roster if attack_on_blue else roster[::-1]), seconds)
        if defense and not (evaluation or aim_calibration) and not second_leg:
            trainer.defense_tactics = defense.assign(trainer.roster, rng, index)
        if offense and not (evaluation or aim_calibration) and not second_leg:
            trainer.offense_tactics = offense.assign(trainer.roster, rng, index)
        if evaluation or aim_calibration:
            # Both sides retain native capper behavior so the pair isolates the role tactics.
            trainer.guided = {}
        elif mode == 'explore' and not second_leg:
            trainer.guided = flank_assignments(trainer.roster, candidates, route_rows, flank_score, rng)
        elif mirrored and defense_setups and not second_leg:
            block_id = index // (2 * len(defense_setups))
            block_routes = report.get('defense_block_routes', {})
            if block_routes.get('block') == block_id:
                plans = block_routes['plans']
            else:
                capper_roster = ((1, 'Capper'),) * attack[0]
                plans = guided_assignments(capper_roster, candidates, route_rows, screening_score, block_id, rng)
            trainer.defense_block_routes = dict(block=block_id, plans=plans)
            slots = [slot for slot, (_, role) in enumerate(trainer.roster, 1) if role == 'Capper']
            trainer.guided = {slots[int(position)-1]: plan for position, plan in plans.items()}
        elif not second_leg:
            trainer.guided = guided_assignments(trainer.roster, candidates, route_rows, screening_score, index, rng)
        trainer.strict_movement = bool(trainer.adaptive_team) or report.get('movement_policy') in ('ski-jet-v1','field-ski-jet-v1')
        trainer.adaptive_movement = bool(trainer.adaptive_team) or report.get('movement_policy') == 'field-ski-jet-v1'
        if trainer.adaptive_movement and trainer.spawn_cohort is None:
            trainer.spawn_cohort = (False, 1)
        trainer.flight_transfer = report.get('flight_transfer', {})
        trainer.human_reference = report.get('human_reference', {})
        trainer.pursuit = report.get('pursuit', {})
        trainer.labels = policy, blue, red, candidate_on_blue
        return trainer

    def save_match(trainer):
        policy, blue, red, candidate_on_blue = trainer.labels
        result = trainer.result
        if evaluation:
            result.update(benchmark_pair=trainer.benchmark_pair, candidate_team=trainer.candidate_team)
            if trainer.adaptive_team:
                result['opponent'] = trainer.benchmark_opponent
                result.setdefault('spawn_fingerprint', None)
            if report['aim_benchmark_profile']:
                result['benchmark_aim_observations'] = assess_trial(result)
        if aim_calibration:
            result.update(aim_pair=trainer.aim_pair, aim_level=trainer.aim_level,
                          candidate_team=trainer.candidate_team, aim_evidence_version=AIM_EVIDENCE_VERSION)
            result['aim_observations'] = assess_trial(result)
            result['aim_sample'] = (result['aim_observations']['teams']
                                    if result['aim_observations']['reason']=='qualified' else None)
        if report.get('mirror_drills') or report.get('mirror_lineups'):
            index = len(report['matches'])
            if report.get('mirror_drills'):
                attack_on_blue = not candidate_on_blue if mode == 'defended' else candidate_on_blue
                attack_team = (1 if attack_on_blue else 2) if mode != 'solo' else trainer.roster[0][0]
                result.update(drill_pair=index // 2 + 1, attack_team=attack_team)
            else:
                result.update(lineup_pair=index // 2 + 1, candidate_team=1 if candidate_on_blue else 2)
            if index % 2:
                report.pop('pending_mirror')
            elif index + 1 < matches:
                report['pending_mirror'] = dict(labels=trainer.labels, roster=trainer.roster, counts=trainer.counts,
                                                routes=trainer.guided, defense=trainer.defense_tactics,
                                                offense=trainer.offense_tactics)
            if hasattr(trainer, 'defense_block_routes'):
                report['defense_block_routes'] = trainer.defense_block_routes
        if trainer.guided:
            result['capper_objective'] = 'flank-exploration-v1' if mode == 'explore' else CAP_SPEED_OBJECTIVE
        frames = trace_frames(result['bots']) if trainer.defense_tactics or trainer.offense_tactics else None
        if trainer.defense_tactics:
            evidence = match_evidence(result, trainer.defense_tactics, frames)
            result.update(defense_evidence_version=EVIDENCE_VERSION, defense_evidence=evidence,
                          defense_tactics={slot: profile for slot, (_, profile) in trainer.defense_tactics.items()})
            if not (evaluation or aim_calibration):
                defense.record(evidence)
        if trainer.offense_tactics:
            evidence = offense_learning.match_evidence(result, trainer.offense_tactics, frames)
            result.update(offense_evidence_version=offense_learning.EVIDENCE_VERSION, offense_evidence=evidence,
                          offense_tactics={slot: profile for slot, (_, profile) in trainer.offense_tactics.items()})
            if not (evaluation or aim_calibration):
                offense.record(evidence)
        margin = (result['blue'] - result['red'])*(1 if candidate_on_blue else -1)
        report['matches'].append(dict(result, policy=policy, blue_policy=blue, red_policy=red, margin=margin))
        if evaluation:
            report['comparison'] = paired_results(report['matches'])
            if report['aim_benchmark_profile']:
                report['benchmark_aim'] = benchmark_aim_report(report['matches'])
        if aim_calibration:
            report['aim_comparison'] = calibration_report([*aim_batches, report['matches']])
        route_rows.extend(guided_evidence((result,), output.name, route_keys))
        publish(path, json.dumps(report, indent=2)+'\n')
        print(f'Team matches complete: {len(report['matches'])}/{matches}', flush=True)

    limit = 1 if evaluation else waves_per_launch
    while len(report['matches']) < matches:
        check_between_matches()
        trainer = prepare_match()
        trainer.waves_per_launch = min(limit, matches-len(report['matches']))
        trainer.verify_start = evaluation or aim_calibration or waves_per_launch > 1
        trainer.next_match, trainer.save_match = prepare_match, save_match
        try:
            start(config, trainer=trainer)
        except RuntimeError as exc:
            if isinstance(exc, NativeMemoryBusy) or type(exc).__name__ == 'NativeResourceBusy':
                print(str(exc), flush=True)
                training_wait(20)
                continue
            if getattr(trainer, 'completed_waves', 0) and any(reason in str(exc) for reason in (
                    'training_reuse_unverified|', 'match_loading_inprogress_phase_required=Result',
                    'match_loading_inprogress_phase_required=WaitingPostMatch')):
                limit = 1
                report.setdefault('reset_fallbacks', []).append(dict(after_match=len(report['matches']), reason=str(exc),
                    wall_seconds=round(time.monotonic()-trainer.wave_began, 2)))
                publish(path, json.dumps(report, indent=2)+'\n')
                print(f'{exc} Completed matches are saved; continuing with fresh games.', flush=True)
            else:
                raise
        finally:
            if trainer.match:
                receipt = json.loads((trainer.match/'host/execution/execution.json').read_bytes())
                if receipt.get('job_active_processes_after_cleanup', receipt.get('job_active_processes_at_parent_exit')) != 0:
                    raise RuntimeError('Team match cleanup could not be verified.')
                cleanup = Campaign.__new__(Campaign)
                cleanup.last_match, cleanup.runs = trainer.match, Path(config['runs']).resolve()
                try:
                    cleanup.retire_game_copy()
                except OSError as exc:
                    print(f'Finished staging copy retained for later cleanup: {exc}', flush=True)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--mode', choices=('solo','defended','screen','teams','scrimmage','offdef','explore','season','flight','duel'), required=True)
    parser.add_argument('--map', default=MAP)
    parser.add_argument('--matches', type=int, required=True)
    parser.add_argument('--bots', type=int, default=5, help='Bots per screening or flight wave.')
    parser.add_argument('--flight-course', choices=('straight','downhill','uphill','recovery'), default='straight')
    parser.add_argument('--waves-per-launch', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--attackers', type=int)
    parser.add_argument('--defenders', type=int)
    parser.add_argument('--team-size', type=int, default=7)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--evaluation', action='store_true')
    parser.add_argument('--aim-calibration', action='store_true')
    args = parser.parse_args()
    if args.aim_calibration and (args.evaluation or args.mode not in ('scrimmage','season')
                                 or args.matches < 2 or args.matches % 2):
        parser.error('Aim calibration needs two games per mirrored pair in a full CTF roster.')
    if not 1 <= args.matches <= 1000 or not 30 <= args.seconds <= 600:
        parser.error('Expected 1â€“1000 matches and 30â€“600 seconds.')
    attack = None
    if args.attackers is not None or args.defenders is not None:
        attack = (args.attackers, args.defenders)
        if (args.mode not in ('solo', 'defended', 'explore') or None in attack or args.attackers < 1 or args.defenders < 0
                or sum(attack) > MAX_TRAINING_BOTS or (args.mode == 'solo' and args.defenders != 0)):
            parser.error(f'Choose at least one capper and at most {MAX_TRAINING_BOTS} total bots.')
    minimum = (2 if args.evaluation or args.aim_calibration else 7) if args.mode == 'scrimmage' else 2 if args.mode == 'season' else 1
    if not minimum <= args.team_size <= MAX_TEAM_BOTS:
        parser.error(f'Expected {minimum}â€“{MAX_TEAM_BOTS} bots per team.')
    config = dict(json.loads(args.config.read_bytes()), training_map=args.map)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == 'screen':
        from paired_flag_screen import main as screen
        root = args.output.parent.parent if args.config == args.output/'practice.json' else args.config.parent
        prior = root/'Campaign-FlagPassSpeed500/progress.json'
        sys.argv[1:] = [str(args.config), str(prior), str(args.output), '--five-bots', '--matches', str(args.matches),
                       '--bots', str(args.bots), '--map', args.map, '--waves-per-launch', str(args.waves_per_launch)]
        screen()
        return
    with (args.output/'campaign.lock').open('a+b') as lock:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        if args.mode == 'flight':
            from flight_training import flight_run
            flight_run(config, args.output, args.matches, args.seconds, args.bots, args.waves_per_launch, args.flight_course)
            return
        if args.mode == 'duel':
            from field_duel import duel_run
            duel_run(config,args.output,args.matches,args.seconds)
            return
        standard_roster = (1, 0) if args.mode == 'solo' else (1, 2)
        checkpoint = args.output/'progress.json'
        legacy_defense = (args.mode == 'defended' and checkpoint.is_file()
                          and 'configuration' in json.loads(checkpoint.read_bytes()))
        legacy_solo = (args.mode == 'solo' and checkpoint.is_file()
                       and 'configuration' in json.loads(checkpoint.read_bytes()))
        if args.mode == 'explore':
            team_run(config, args.output, args.matches, args.seconds, args.seed, args.team_size,
                     attack or (2, 2), args.mode, args.waves_per_launch)
        elif (args.mode == 'defended' and not legacy_defense) or (args.mode == 'solo' and not legacy_solo):
            team_run(config, args.output, args.matches, args.seconds, args.seed, args.team_size,
                     attack or standard_roster, args.mode, args.waves_per_launch)
        elif args.mode in ('teams', 'scrimmage', 'offdef', 'season') or (attack is not None and attack != standard_roster):
            team_run(config, args.output, args.matches, args.seconds, args.seed, args.team_size, attack, args.mode,
                     args.waves_per_launch, evaluation=args.evaluation, aim_calibration=args.aim_calibration)
        else:
            campaign = (FreshDefense(args.output,args.matches,args.seed,grounded=True)
                        if args.mode == 'defended' else FreshSolo(args.output,args.matches,76,args.seed))
            campaign.map_id = args.map
            campaign.trials_per_match = args.waves_per_launch
            campaign.load_history(args.mode)
            run(config,campaign)


if __name__ == '__main__':
    if len(sys.argv) > 2 and Path(sys.argv[2]).parent.name == 'DashboardRuns':
        output = Path(sys.argv[2])
        with (output.parent/'worker.lock').open('a+b') as lock:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            os.environ['T3_DASHBOARD_STOP_FILE'] = str(output/'stop.request')
            (output/'cooperative-stop').touch()
            try:
                status = output/'status.json'
                if status.is_file() and json.loads(status.read_bytes()).get('status') == 'Queued':
                    status.unlink()
                check_between_matches()
                main()
            except TrainingPaused:
                publish(output/'status.json', '{"status":"Paused"}\n')
                print('Training paused. Completed results are saved.', flush=True)
            except TrainingStopped:
                publish(output/'status.json', '{"status":"Stopped"}\n')
                print('Training stopped. Completed results are saved.', flush=True)
            except BaseException as exc:
                message = str(exc)
                role = re.search(r'training_role_asset_missing=([a-z_]+)', message)
                if role:
                    message = 'The installed game has no verified bot profile for ' + role[1].replace('_', ' ') + '.'
                elif message == 'Timed out waiting for native training evidence.':
                    message = 'The local match timed out. Completed matches are still saved.'
                elif 'match_rules_bot_slots_exhausted' in message:
                    message = 'The local host ran out of bot roster slots. Completed matches are still saved.'
                elif 'hill_course_unavailable|' in message:
                    message = 'A usable hill could not be verified for every bot. Try fewer bots or another map.'
                elif 'hill_start_' in message:
                    message = 'One or more bots could not settle at the uphill start. Try fewer bots or another map.'
                elif 'flight_recovery_' in message:
                    message = 'The trainer could not verify a low-energy shove for every bot. Try fewer bots or another map.'
                elif 'field_duel_' in message:
                    message = 'The trainer could not verify the duel starting positions and native flag pickup on this map.'
                elif 'field_benchmark_insufficient_native_starts|' in message:
                    message = 'This map does not have separate native starts for training and evaluation.'
                elif message not in ('Open Steam and sign in before starting local practice.',
                                     'Close the existing TRIBES 3 game before opening local practice.',
                                     MISSING_GAME_CACHE,
                                     'The selected map is unavailable for local bot training.'):
                    message = 'The trainer exited early. Saved matches can be resumed.'
                publish(output/'status.json', json.dumps(dict(status='Failed', message=message))+'\n')
                raise
            else:
                publish(output/'status.json', '{"status":"Complete"}\n')
    else:
        main()
