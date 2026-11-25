"""Measure fly-through flag pickups against matched braking controls."""
import argparse
from dataclasses import asdict, replace
import errno
import json
import msvcrt
from pathlib import Path
from statistics import median
import time

from batch import run
from defense_batch import BodyBlockTrainer, DefenseCampaign
from practice import HERE
from train import Policy, publish, replace_once, summarize


# Signed lateral route, distance behind the flag before turning toward home.
ROUTES = (('braking', 0, 0), ('right_45m', 1, 4500),
          ('left_45m', -1, 4500), ('right_70m', 1, 7000), ('left_70m', -1, 7000))
STARTS = ((1, -40), (2, 0), (3, 40), (3, -65))
DEFENSES = (4, 6)
LONG_RUNUPS = (9500, 12500, 7000)


class VerifiedResetTrainer(BodyBlockTrainer):
    def instrument(self, text, out):
        text = super().instrument(text, out)
        script = json.dumps((HERE / 'verify_trial_reset.lua').as_posix())
        return replace_once(text, '  body_block=true,', f'  verify_reuse=true,reuse_script={script},body_block=true,')


class LongRunupTrainer(BodyBlockTrainer):
    def instrument(self, text, out):
        return replace_once(super().instrument(text, out), '  body_block=true,', '  long_runups=true,body_block=true,')


class SpeedSweepTrainer(LongRunupTrainer):
    def instrument(self, text, out):
        return replace_once(super().instrument(text, out), '  long_runups=true,', '  speed_sweep=true,long_runups=true,')


class FlagPassCampaign(DefenseCampaign):
    starts = STARTS

    def __init__(self, output, prior, pilot=None, *, reset_mode=None, validation=False, long_runups=False):
        self.reset_mode = 'fresh' if long_runups else reset_mode
        self.long_runups = long_runups
        self.validation = validation
        if validation and pilot is None:
            raise ValueError('Reset validation needs the finished pilot.')
        self.clock_started = None
        if (prior['configuration'].get('scenario') != 'juggernaut-body-block-v1'
                or prior['completed'] != prior['configuration']['attempts']):
            raise ValueError('Use the completed Juggernaut checkpoint.')
        baseline = Policy(**prior['configuration']['capper_policy'])
        self.routes = {name: (replace(baseline, flank=side), runup, None) for name, side, runup in ROUTES}
        scenario = 'flag-pass-pilot-v1'
        if pilot is not None:
            if pilot['configuration'].get('scenario') != scenario or pilot['completed'] != 40:
                raise ValueError('The larger run requires all 40 pilot trials.')
            self.starts = ((1, -85), (1, 75), (2, -75), (2, 85), (3, -95), (3, 95))
            best = sorted(tuple(self.routes)[1:],
                          key=lambda name: self.pilot_route_rank(pilot, name), reverse=True)[:2]
            for name in best:
                route, runup, _ = self.routes[name]
                self.routes[name+'_lift'] = (route, runup, 1)
                self.routes[name+'_early_lift'] = (route, runup, 2)
            scenario = 'flag-pass-altitude-v1'
        self.plan = []
        for index, (spawn, offset) in enumerate(self.starts):
            for defense in DEFENSES[::1 if index % 2 == 0 else -1]:
                names = tuple(self.routes)
                for name in names[index:] + names[:index]:
                    self.plan.append(((name, defense), spawn, offset, None))
        if long_runups:
            scenario = 'flag-pass-long-runup-v1'
            self.starts = ((1, -85), (2, 85), (3, 95))
            self.routes = {
                f'{label}_{runup // 100}m_early_lift': (replace(baseline, flank=side, ski=1), runup, 2)
                for runup in LONG_RUNUPS for label, side in (('left', -1), ('right', 1))
            }
            names = tuple(self.routes)
            self.plan = [
                ((name, DEFENSES[index % len(DEFENSES)]), spawn, offset, None)
                for index, (spawn, offset) in enumerate(self.starts)
                for name in names[index:] + names[:index]
            ]
        if validation:
            scenario = 'flag-pass-reset-validation-v1'
            self.plan = self.validation_plan(pilot)
        super().__init__(output, len(self.plan), 2026, grounded=True, scenario=scenario)
        self.training_total = self.total

    @staticmethod
    def validation_plan(pilot):
        eligible = [row for row in pilot['attempts'] if
                    not any(row['defense'][key] for key in ('died', 'damage_taken', 'red_caps'))]
        grabs = [row for row in eligible if row['pickup']][:2]
        misses = sorted((row for row in eligible if not row['pickup']),
                        key=lambda row: row['closest_pass_cm'])

        def request(row):
            policy = row['approach_route'], row['defense_profile']
            return policy, row['spawn'], row['offset_cm'], None

        plan = []
        for row in (*grabs, *misses[:4-len(grabs)]):
            # A no-grab primer exercises movement without advancing the match score.
            primer = next((miss for miss in misses if miss['defense_profile'] == row['defense_profile']), None)
            if primer is not None:
                plan.extend((request(row), request(primer), request(row)))
        return plan

    @staticmethod
    def pilot_route_rank(pilot, name):
        rows = [row for row in pilot['attempts'] if row['approach_route'] == name]
        homeward = [row for row in rows if row['pickup'] and not row['recovered']
                    and row['grab_homeward_kmh'] > 0]
        first_pass = sum(bool(row['pickup']) and not row['recovered'] for row in rows)
        return (len(homeward), first_pass, -median(row['closest_pass_cm'] for row in rows),
                median(row['closest_pass_kmh'] for row in rows))

    def policy_configuration(self):
        self.policies = tuple(dict.fromkeys(policy for policy, *_ in self.plan))
        configuration = dict(routes={name: dict(policy=asdict(policy), runup_cm=runup,
                                      **({'guidance': guidance} if guidance is not None else {}))
                            for name, (policy, runup, guidance) in self.routes.items()},
                    starts=[list(start) for start in self.starts], defense_profiles=list(DEFENSES))
        if self.reset_mode:
            configuration['reset_mode'] = self.reset_mode
        if self.validation:
            configuration['matched_plan'] = [[list(policy), spawn, offset] for policy, spawn, offset, _ in self.plan]
        return configuration

    def make_trainer(self):
        self.clock_started = time.monotonic()
        trainer = BodyBlockTrainer
        if self.long_runups:
            trainer = LongRunupTrainer
        elif self.reset_mode == 'verified':
            trainer = VerifiedResetTrainer
        return trainer(0, self.seconds, self.seed, False, batch=self.play)

    def play(self, out, count, attempt):
        self.attempt_started = self.clock_started
        super().play(out, count, attempt)

    def end_match_after(self, row):
        return (self.reset_mode == 'fresh'
                or (self.reset_mode == 'verified' and row['capture'])
                or (self.validation and (row['campaign_attempt'] % 3 != 2 or row['pickup']))
                or super().end_match_after(row))

    def trial_plan(self, index, history, rng):
        return self.plan[index]

    def played_policy(self, row):
        return row['approach_route'], row['defense_profile']

    def play_attempt(self, attempt, policy, spawn, offset, evaluating):
        name, defense = policy
        route, runup, guidance = self.routes[name]
        row = attempt(route, spawn, offset, evaluating, defense_profile=defense,
                      pass_runup_cm=runup, pass_guidance=guidance)
        if self.reset_mode:
            row['verified_reuse'] = False
            if self.reset_mode == 'verified' and row['id'] > 1:
                marker = self.last_match / f'verified-reset-{int(row["id"])}.csv'
                if not marker.is_file() or marker.read_text().strip() != '1':
                    raise RuntimeError('training_reuse_unverified|missing_reset_evidence')
                row['verified_reuse'] = True
            finished = time.monotonic()
            row['wall_seconds'] = round(finished - self.attempt_started, 2)
            self.attempt_started = finished
        return dict(row, approach_route=name, defense_profile=defense, pass_runup_cm=runup)

    @staticmethod
    def pass_summary(rows):
        grabs = [row for row in rows if row['pickup']]
        first_pass = [row for row in grabs if not row['recovered']]
        homeward = [row for row in first_pass if row['grab_homeward_kmh'] > 0]
        misses = [row for row in rows if not row['pickup'] or row['recovered']]
        fastest = max(first_pass, key=lambda row: row['grab_kmh'], default=None)
        return dict(
            **summarize(rows),
            first_pass_grabs=len(first_pass),
            recovery_grabs=len(grabs)-len(first_pass),
            homeward_grabs=len(homeward),
            first_pass_200_kmh=sum(row['grab_kmh'] >= 200 for row in first_pass),
            homeward_200_kmh=sum(row['grab_kmh'] >= 200 for row in homeward),
            homeward_330_kmh=sum(row['grab_kmh'] >= 330 for row in homeward),
            homeward_200_kmh_captures=sum(row['grab_kmh'] >= 200 and bool(row['capture']) for row in homeward),
            **(dict(skiing_flythrough_grabs=sum(row['skiing_flythrough_grab'] for row in grabs),
                    skiing_homeward_flythrough_grabs=sum(row['skiing_flythrough_grab']
                        and row['grab_homeward_kmh'] > 0 for row in grabs))
               if rows and all('skiing_flythrough_grab' in row for row in rows) else {}),
            median_missed_pass_distance_m=round(median(row['closest_pass_cm'] for row in misses)/100, 2) if misses else None,
            median_first_pass_grab_kmh=round(median(row['grab_kmh'] for row in first_pass), 2) if first_pass else None,
            median_first_pass_homeward_kmh=round(median(row['grab_homeward_kmh'] for row in first_pass), 2) if first_pass else None,
            fastest_first_pass_grab={key: fastest[key] for key in
                ('grab_kmh', 'grab_homeward_kmh', 'capture', 'trace')} if fastest else None,
        )

    def report_fields(self):
        return dict(flag_pass=self.pass_summary(self.rows), by_route={
            name: self.pass_summary([row for row in self.rows if row['approach_route'] == name])
            for name in self.routes
        })


class SpeedSweepCampaign(FlagPassCampaign):
    references = ('left_70m_early_lift', 'right_95m_early_lift')
    search_count = 400
    trial_count = 500
    search_starts = ((1, -85), (1, 75), (2, -75), (2, 85), (3, 95))
    test_starts = tuple((spawn, offset) for spawn in (1, 2, 3)
                        for offset in (-65, -25, 0, 25, 65, 90)) + (
                            (1, 95), (1, -95), (2, 95), (2, -95), (3, -95), (3, -85), (3, 85))

    def __init__(self, output, prior):
        self.reset_mode = 'fresh'
        self.validation = False
        self.long_runups = True
        self.starts = self.search_starts
        self.clock_started = None
        if (prior['configuration'].get('scenario') != 'juggernaut-body-block-v1'
                or prior['completed'] != prior['configuration']['attempts']):
            raise ValueError('Use the completed Juggernaut checkpoint.')
        baseline = Policy(**prior['configuration']['capper_policy'])
        lift_names = {2: 'early_lift', 3: '80m_low_lift', 4: '100m_low_lift', 5: '80m_high_lift'}
        self.routes = {
            f'{name}_{distance // 100}m_{lift_names[lift]}': (replace(baseline, flank=side, ski=1), distance, lift)
            for distance in (4500, 7000, 8500, 9500, 12500)
            for lift in lift_names for name, side in (('left', -1), ('right', 1))
        }
        self.plan = []
        names = list(self.routes)
        for cohort, (spawn, offset) in enumerate(self.starts):
            for defense in DEFENSES:
                # Put a spread of distances and lift profiles in the first block.
                shift = (cohort * 7 + DEFENSES.index(defense) * 13) % len(names)
                order = names[shift:] + names[:shift]
                self.plan.extend(((name, defense), spawn, offset, None) for name in order[::9]
                                 + [name for index, name in enumerate(order) if index % 9])
        assert len(self.plan) == self.search_count and len(self.test_starts) * 4 == self.trial_count - self.search_count
        DefenseCampaign.__init__(self, output, self.trial_count, 2026, grounded=True, scenario='flag-pass-speed-sweep-v1')
        self.training_total = self.search_count

    def policy_configuration(self):
        config = super().policy_configuration()
        config.update(search_attempts=self.search_count, test_starts=[list(start) for start in self.test_starts],
                      references=list(self.references), route_order=[name for (name, _), *_ in self.plan])
        return config

    def make_trainer(self):
        self.clock_started = time.monotonic()
        return SpeedSweepTrainer(0, self.seconds, self.seed, False, batch=self.play)

    @staticmethod
    def speed_rank(rows):
        grabs = [row for row in rows if row.get('skiing_flythrough_grab') and row['grab_homeward_kmh'] > 0]
        passes = [row for row in rows if row.get('entered_flythrough')]
        # Use speed at a successful pickup first. Near misses are evidence for route
        # selection only and never count as successful grabs.
        return (len(grabs), median(row['grab_kmh'] for row in grabs) if grabs else 0,
                sum(row['capture'] for row in grabs), sum(row['flythrough_gap_cm'] <= 500 for row in passes),
                -median(row['flythrough_gap_cm'] for row in passes) if passes else float('-inf'),
                median(row['flythrough_speed_kmh'] for row in passes) if passes else 0)

    def selected_routes(self):
        groups = {}
        for row in self.rows[:self.search_count]:
            groups.setdefault(row['approach_route'], []).append(row)
        candidates = [name for name in self.routes if name not in self.references and name in groups]
        return tuple(sorted(candidates, key=lambda name: self.speed_rank(groups[name]), reverse=True)[:2])

    def trial_plan(self, index, history, rng):
        if index < self.search_count:
            return self.plan[index]
        group, position = divmod(index - self.search_count, 4)
        entries = tuple(zip((*self.references, *self.selected_routes()),
                            ('reference_70m', 'reference_95m', 'candidate_1', 'candidate_2'), strict=True))
        name, role = entries[(position + group) % len(entries)]
        spawn, offset = self.test_starts[group]
        return (name, DEFENSES[group % len(DEFENSES)]), spawn, offset, role

    def evaluation_settings(self, row):
        return dict(approach_route=row['approach_route'], policy=row['policy'])

    def report_fields(self):
        return dict(**super().report_fields(), selected_routes=list(self.selected_routes()) if
                    len(self.rows) >= self.search_count else [],
                    search_flag_pass=self.pass_summary(self.rows[:self.search_count]),
                    held_out_flag_pass=self.pass_summary(self.rows[self.search_count:]))


def qualify_reuse(campaign):
    pairs = []
    for start in range(0, len(campaign.rows) - 2, 3):
        fresh, _, warm = campaign.rows[start:start+3]
        if not warm['verified_reuse']:
            continue
        same_outcome = all(fresh[key] == warm[key] for key in ('pickup', 'capture', 'recovered'))
        differences = {key: abs(fresh[key] - warm[key]) for key in (
            'average_kmh', 'peak_kmh', 'closest_pass_cm', 'seconds'
        )}
        if fresh['pickup'] and warm['pickup']:
            differences.update({key: abs(fresh[key] - warm[key]) for key in (
                'grab_kmh', 'grab_homeward_kmh', 'pickup_seconds'
            )})
        differences['damage_taken'] = abs(fresh['defense']['damage_taken'] - warm['defense']['damage_taken'])
        pairs.append(dict(fresh=fresh['campaign_attempt'], warm=warm['campaign_attempt'],
                          same_outcome=same_outcome, differences=differences,
                          seconds_saved=round(fresh['wall_seconds'] - warm['wall_seconds'], 2)))
    limits = dict(average_kmh=5, peak_kmh=10, closest_pass_cm=300, seconds=3, grab_kmh=5,
                  grab_homeward_kmh=8, pickup_seconds=3, damage_taken=100)
    paired_grabs = sum('grab_kmh' in pair['differences'] for pair in pairs)
    median_saved = median(pair['seconds_saved'] for pair in pairs) if pairs else None
    reasons = []
    if len(pairs) < 4 or paired_grabs < 2:
        reasons.append('Fewer than four verified pairs or two paired grabs.')
    if any(not pair['same_outcome'] or any(value > limits[key] for key, value in pair['differences'].items())
           for pair in pairs):
        reasons.append('Matched gameplay differed beyond the preset tolerances.')
    if median_saved is None or median_saved <= 0:
        reasons.append('No measured wall-clock savings.')
    return dict(reset_mode='fresh' if reasons else 'verified', reasons=reasons, pairs=pairs,
                paired_grabs=paired_grabs, median_wall_seconds_saved=median_saved, limits=limits)


def complete_pilot(folder, config, prior):
    print(f'Waiting for the pilot at {folder / "progress.json"}.', flush=True)
    with (folder / 'campaign.lock').open('r+b') as lock:
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno != errno.EACCES:
                    raise
                time.sleep(20)
        campaign = FlagPassCampaign(folder, prior)
        if len(campaign.rows) < campaign.total:
            print(f'Resuming the pilot from {len(campaign.rows)}/{campaign.total}.', flush=True)
            run(config, campaign)
        return json.loads(campaign.checkpoint.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('prior', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--after-pilot', type=Path, help='Finish or wait for the pilot before expanding it.')
    parser.add_argument('--qualify-reuse', action='store_true', help='Compare fresh and reset matches before expanding.')
    parser.add_argument('--long-runups', action='store_true', help='Compare longer runups against 70 m references.')
    parser.add_argument('--speed-sweep', action='store_true', help='Run 400 speed trials and 100 held-out trials.')
    args = parser.parse_args()
    if args.speed_sweep and (args.long_runups or args.after_pilot or args.qualify_reuse):
        parser.error('--speed-sweep starts a separate 500-trial batch.')
    if args.long_runups and (args.after_pilot or args.qualify_reuse):
        parser.error('--long-runups starts a separate matched batch.')
    if args.qualify_reuse and not args.after_pilot:
        parser.error('--qualify-reuse requires --after-pilot.')
    prior = json.loads(args.prior.read_bytes())
    config = json.loads(args.config.read_bytes())
    if args.after_pilot and args.after_pilot.resolve() == args.output.resolve():
        parser.error('The pilot and expansion need distinct campaign directories.')
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'campaign.lock').open('a+b') as lock:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        pilot = None
        if args.after_pilot:
            pilot = complete_pilot(args.after_pilot, config, prior)
        reset_mode = None
        if args.qualify_reuse:
            validation_dir = args.output / 'reset-validation'
            validation_dir.mkdir(exist_ok=True)
            validation = FlagPassCampaign(validation_dir, prior, pilot, reset_mode='verified', validation=True)
            print(f'Validating native resets with {validation.total} matched trials.', flush=True)
            run(config, validation)
            decision_path = validation_dir / 'decision.json'
            if decision_path.exists():
                decision = json.loads(decision_path.read_bytes())
            else:
                decision = qualify_reuse(validation)
                publish(decision_path, json.dumps(decision, indent=2) + '\n')
            reset_mode = decision['reset_mode']
            print(f'Expansion mode: {reset_mode}. {" ".join(decision["reasons"])}', flush=True)
        campaign = (SpeedSweepCampaign(args.output, prior) if args.speed_sweep else
                    FlagPassCampaign(args.output, prior, pilot=pilot, reset_mode=reset_mode,
                                     long_runups=args.long_runups))
        run(config, campaign)


if __name__ == '__main__':
    main()
