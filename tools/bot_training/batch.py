"""Run a resumable series of native bot trials across local matches."""
import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import random
import shutil
from statistics import mean
import time
import msvcrt

from practice import NativeMemoryBusy, check_between_matches, check_training_stop, memory_available, start, training_wait
from train import FASTER_APPROACH, FLANKS, KNOWN_PICKUP, Policy, Trainer, publish, rank, reward, summarize


CHALLENGERS = (
    KNOWN_PICKUP,
    replace(FASTER_APPROACH, approach_cm=2200),
    replace(FASTER_APPROACH, turn=0),
    replace(FASTER_APPROACH, pulse=.40, period=2.2),
    *FLANKS,
)
POLICIES = (FASTER_APPROACH, *CHALLENGERS)
HELD_OUT = ((1, -80), (2, 80), (3, 0), (3, -80), (3, 80))


def select(history, rng, baseline=FASTER_APPROACH, score=reward):
    trials = sum(map(len, history.values()))
    if not trials:
        return baseline
    unseen = [policy for policy, rows in history.items() if not rows]
    if unseen:
        return rng.choice(unseen)
    return max(history, key=lambda policy: mean(map(score, history[policy]))
               + math.sqrt(2 * math.log(trials + 1) / len(history[policy])))


def champion(history):
    tested = [policy for policy, rows in history.items() if rows]
    # Require repeat evidence before a challenger can replace the known baseline.
    eligible = [policy for policy in tested if len(history[policy]) >= 3]
    return max(eligible or tested, key=lambda policy: (
        mean(row['capture'] for row in history[policy]), mean(map(reward, history[policy]))))


class Campaign:
    held_out_starts = HELD_OUT
    trials_per_match = 7

    def __init__(self, root, total, seconds, seed, prior=None, scenario=None):
        self.root = root
        self.total, self.seconds, self.seed = total, seconds, seed
        self.checkpoint = root / 'progress.json'
        self.baseline = FASTER_APPROACH
        self.policies = POLICIES
        if prior:
            groups = {}
            for row in prior['attempts']:
                if row['held_out']:
                    groups.setdefault(row['evaluation_role'], []).append(row)
            if set(groups) != {'baseline', 'selected'} or len(groups['baseline']) != len(groups['selected']):
                raise ValueError('The prior campaign needs a complete matched evaluation.')
            winning_role = max(('baseline', 'selected'), key=lambda role: rank(groups[role]))
            self.baseline = Policy(**groups[winning_role][0]['policy'])
            self.policies = self.candidates(self.baseline)
        self.spec = dict(version=1, attempts=total, seconds=seconds, seed=seed,
                         **self.policy_configuration())
        if prior:
            self.spec['starting_policy'] = asdict(self.baseline)
        if scenario:
            self.spec['scenario'] = scenario
        if self.held_out_starts != HELD_OUT:
            self.spec['held_out_starts'] = [list(start) for start in self.held_out_starts]
        self.training_total = total - min(10, max(2, total // 5 * 2)) if total >= 12 else total
        self.rows = []
        self.last_match = None
        self.runs = None
        if self.checkpoint.exists():
            previous = json.loads(self.checkpoint.read_bytes())
            if previous['configuration'] != self.spec:
                raise ValueError('Use the same settings to resume, or choose a new campaign directory.')
            self.rows = previous['attempts']

    def candidates(self, baseline):
        refined = tuple(replace(baseline, approach_cm=distance) for distance in (2000, 2400, 3200, 3600))
        return tuple(dict.fromkeys((baseline, *POLICIES, *refined)))

    def policy_configuration(self):
        return dict(policies=[asdict(policy) for policy in self.policies])

    def make_trainer(self):
        return Trainer(0, self.seconds, self.seed, False, batch=self.play)

    def retire_game_copy(self):
        if self.last_match is None:
            return
        run = self.last_match.resolve(strict=True)
        game = run / 'host/game'
        if game.is_dir():
            # rmtree on Windows removes directory junctions as links.
            if (run.parent != self.runs or game.resolve(strict=True) != run / 'host/game'
                    or not run.name.startswith('training-')):
                raise ValueError('Unexpected game staging path.')
            shutil.rmtree(game)

    def write(self):
        history = [row for row in self.rows if not row['held_out']]
        evaluated = [row for row in self.rows if row['held_out']]
        groups = {}
        for row in evaluated:
            groups.setdefault(row['evaluation_role'], []).append(row)
        report = dict(configuration=self.spec, completed=len(self.rows), summary=summarize(self.rows),
                      training=summarize(history), evaluation={
                          key: dict(**self.evaluation_settings(rows[0]), **summarize(rows)) for key, rows in groups.items()
                      }, attempts=self.rows, **self.report_fields())
        for retry in range(20):
            try:
                publish(self.checkpoint, json.dumps(report, indent=2) + '\n')
                return
            except PermissionError:
                if retry == 19:
                    raise
                time.sleep(.1)

    def report_fields(self):
        return {}

    def learning_history(self):
        return ()

    def evaluation_settings(self, row):
        return dict(policy=row['policy'])

    def played_policy(self, row):
        return Policy(**row['policy'])

    def select_policy(self, history, rng):
        return select(history, rng, self.baseline)

    def evaluation_policy(self, history):
        return champion(history)

    def play_attempt(self, attempt, policy, spawn, offset, evaluating):
        return attempt(policy, spawn, offset, evaluating)

    def trial_plan(self, index, history, rng):
        if index < self.training_total:
            policy = self.select_policy(history, rng)
            return policy, rng.randint(1, 2), rng.choice((-40, 0, 40)), None
        pair, side = divmod(index - self.training_total, 2)
        spawn, offset = self.held_out_starts[pair]
        policy = self.evaluation_policy(history) if side else self.baseline
        return policy, spawn, offset, 'selected' if side else 'baseline'

    def end_match_after(self, row):
        defense = row.get('defense')
        return bool(defense and (
            defense['died'] or defense['damage_taken'] or defense['red_caps']
            or min(defense['hof_alive_seconds'], defense['ld_alive_seconds']) < row['seconds'] - 1
        ))

    def play(self, out, count, attempt):
        self.last_match = out
        if count < 3:
            raise ValueError('The batch requires the three High Octane starts.')
        history = {policy: [] for policy in self.policies}
        prior_rows = self.learning_history()
        for row in (*prior_rows, *self.rows):
            if not row['held_out']:
                history[self.played_policy(row)].append(row)
        captures = 0
        # Limit normal match time to leave room for slow flag returns and keep the
        # original five-capture win condition. The fifth capture is already on disk.
        deadline = time.monotonic() + 650
        for _ in range(self.trials_per_match):
            index = len(self.rows)
            if index >= self.total or captures == 5 or time.monotonic() >= deadline:
                break
            rng_index = index + len(prior_rows) if index < self.training_total else index
            rng = random.Random(f'{self.seed}:{rng_index}')
            policy, spawn, offset, role = self.trial_plan(index, history, rng)
            evaluating = role is not None
            row = self.play_attempt(attempt, policy, spawn, offset, evaluating)
            row.update(campaign_attempt=index + 1, evaluation_role=role,
                       trace=str((out / row['trace']).resolve()))
            self.rows.append(row)
            self.write()
            if not evaluating:
                history[policy].append(row)
            captures += int(row['capture'])
            print(f'Campaign progress {len(self.rows)}/{self.total}', flush=True)
            check_between_matches()
            if self.end_match_after(row):
                break


def run(config, campaign):
    campaign.runs = Path(config['runs']).resolve()
    campaign.write()
    retries = 0
    while len(campaign.rows) < campaign.total:
        check_training_stop()
        campaign.last_match = None
        if memory_available() < 5 * 1024**3:
            print('Waiting for 5 GiB of available Windows commit.', flush=True)
            while memory_available() < 5 * 1024**3:
                training_wait(20)
        saved = len(campaign.rows)
        try:
            start(config, trainer=campaign.make_trainer())
        except RuntimeError as exc:
            if isinstance(exc, NativeMemoryBusy):
                training_wait(20)
                continue
            if type(exc).__name__ == 'NativeResourceBusy':
                print('Another Unreal task has the test slot. Retrying in 20 seconds.', flush=True)
                training_wait(20)
                continue
            recoverable = ('training_reset_position', 'training_teleport_failed', 'training_reset_settle_timeout',
                           'Local host exited', 'Timed out waiting for native training evidence',
                           'match_loading_inprogress_phase_required=Result', 'training_reuse_unverified')
            if len(campaign.rows) > saved:
                retries = 0
            if retries >= 2 or not any(reason in str(exc) for reason in recoverable):
                raise
            retries += 1
            print(f'Retrying in a fresh match after {exc}', flush=True)
            if campaign.last_match:
                try:
                    campaign.retire_game_copy()
                except OSError as cleanup_error:
                    print(f'Could not remove the finished match staging copy: {cleanup_error}', flush=True)
        else:
            retries = 0
            try:
                campaign.retire_game_copy()
            except OSError as exc:
                print(f'Could not remove the finished match staging copy: {exc}', flush=True)
    print(f'Finished {len(campaign.rows)} native attempts. Results: {campaign.checkpoint}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--attempts', type=int, default=100)
    parser.add_argument('--seconds', type=int, default=76)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--after', type=Path, help='Require a completed campaign checkpoint before starting.')
    args = parser.parse_args()
    if not 1 <= args.attempts <= 10000 or not 3 <= args.seconds <= 90:
        parser.error('Use 1–10,000 attempts and 3–90 seconds per attempt.')
    prior = None
    if args.after:
        prior = json.loads(args.after.read_bytes())
        if prior['completed'] != prior['configuration']['attempts']:
            parser.error('The prior campaign must finish before scaling up.')
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'campaign.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            parser.error('Another trainer is already using this campaign directory.')
        run(json.loads(args.config.read_bytes()), Campaign(args.output, args.attempts, args.seconds, args.seed, prior))


if __name__ == '__main__':
    main()
