"""Train and compare movement settings in an isolated High Octane native host."""
import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
from statistics import median
import time

from practice import HERE, event_text, memory_available, start


@dataclass(frozen=True)
class Policy:
    pulse: float
    period: float
    ski: int
    turn: float


BASELINE = Policy(0, 2, 0, 0)
POLICIES = [BASELINE, Policy(0, 2, 1, 0)] + [
    Policy(pulse, period, 1, turn)
    for pulse, period in ((.25, 1.8), (.5, 2.5), (.9, 3.5))
    for turn in (-8, 0, 8)
]
METRICS = ('id', 'capture', 'pickup', 'seconds', 'initial_cm', 'closest_cm',
           'displacement_cm', 'jet_frames', 'ski_frames', 'start_energy')


def replace_once(source, anchor, replacement):
    if source.count(anchor) != 1:
        raise ValueError(f'The native practice template changed at {anchor!r}.')
    return source.replace(anchor, replacement, 1)


def publish(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(data, encoding='utf-8')
    temp.replace(path)


def reward(result):
    progress = 1 - min(1, result['closest_cm'] / max(1, result['initial_cm']))
    return 4 * result['capture'] + 2 * result['pickup'] + progress


def rank(results):
    captures = [row['seconds'] for row in results if row['capture']]
    return (len(captures), -median(captures) if captures else 0,
            sum(row['pickup'] for row in results), sum(reward(row) for row in results))


class Trainer:
    def __init__(self, attempts, seconds, seed, smoke):
        self.attempts, self.seconds, self.smoke = attempts, seconds, smoke
        self.rng = random.Random(seed)
        self.seed = seed

    def instrument(self, text, run):
        stamp = "  local stamp=now();assert(finite(stamp),'match_loading_clock_unknown')"
        text = replace_once(text, stamp,
            "  assert(env.allow_loopback and env.map_id=='HighOctane2026' and committed.count==1)\n"
            "  count=1;teams[2]=true\n" + stamp)
        hook = ' function service.populate(gm,gs,roster,revision)'
        text = replace_once(text, hook, f'''
 local train=assert(loadfile({json.dumps((HERE / 'native_trials.lua').as_posix())}))()({{
  path={json.dumps(run.as_posix())},scope=scope,signature=signature,report=report,valid=valid
 }})
 local training_started=false
''' + hook + '''
  if training_started then return end
''')
        ready = "   report('MATCH_RULES_BOTS_READY|count='..ready)"
        text = replace_once(text, ready, ready + '''
   local entry=assert(entries[1])
   assert(#entries==1 and entry.team==1 and entry.pawn and entry.controller,'training_single_blue_bot')
   training_started=true
   local ok, why=pcall(train,gm,gs,entry.pawn,entry.controller)
   if not ok then report('BOT_TRAIN_ERROR|'..tostring(why):sub(1,400)) end
''')
        return replace_once(text, ',flag_approach=botFlagApproach', '')

    def wait(self, out, process, ready, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            log = event_text(out / 'host')
            for line in log.splitlines():
                if line.startswith(('RUNTIME_ERROR|', 'BOT_TRAIN_ERROR|')):
                    raise RuntimeError(line)
            if process.done():
                raise RuntimeError('Local host exited. Check host/game.log in the training run.')
            if memory_available() < 1024**3:
                raise RuntimeError('Available commit dropped below the game reserve.')
            result = ready(log)
            if result:
                return result
            time.sleep(.25)
        raise RuntimeError('Timed out waiting for native training evidence.')

    def run(self, out, process):
        def spawn_count(log):
            for line in log.splitlines():
                if line.startswith('BOT_TRAIN_READY|'):
                    return int(line.split('|')[1])

        count = self.wait(out, process, spawn_count, 420)
        if count < 2:
            raise ValueError('Native training requires at least two distinct spawn positions.')
        print(f'Native training host ready with {count} starting positions.', flush=True)
        history = {policy: [] for policy in POLICIES}
        trial = 0

        def attempt(policy, spawn, offset, evaluation):
            nonlocal trial
            trial += 1
            path = out / f'result-{trial}.csv'
            values = [spawn, offset, self.seconds, *asdict(policy).values()]
            publish(out / f'trial-{trial}.csv', ','.join(map(str, values)) + '\n')
            self.wait(out, process, lambda _: path.is_file(), self.seconds * 4 + 40)
            row = dict(zip(METRICS, map(float, path.read_text().strip().split(',')), strict=True))
            if (not all(map(math.isfinite, row.values())) or row['id'] != trial or row['start_energy'] < 98
                    or row['pickup'] not in (0, 1) or row['capture'] not in (0, row['pickup'])):
                raise ValueError(f'Invalid result for native trial {trial}.')
            with (out / 'trials.jsonl').open('a', encoding='utf-8') as log:
                log.write(json.dumps(dict(row, policy=asdict(policy), reward=reward(row),
                                          spawn=spawn, offset_cm=offset, held_out=evaluation)) + '\n')
            print(f"Trial {trial}: moved {row['displacement_cm']/100:.1f} m, "
                  f"pickup {int(row['pickup'])}, capture {int(row['capture'])}, reward {reward(row):.3f}", flush=True)
            return row

        if self.smoke:
            results = [attempt(BASELINE, 1, 0, False), attempt(Policy(.9, 2, 1, 0), count, 0, True)]
            assert all(row['displacement_cm'] >= 100 for row in results), 'Native bot failed to move.'
            assert results[1]['jet_frames'] > 0, 'Native jet input did not activate.'
            publish(out / 'smoke.json', json.dumps({'verified_trials': len(results), 'results': results}, indent=2))
            return

        for index in range(self.attempts):
            # Upper-confidence-bound selection balances measured reward and exploration.
            policy = max(POLICIES, key=lambda item: (
                sum(map(reward, history[item])) / len(history[item])
                + math.sqrt(2 * math.log(index + 1) / len(history[item])) if history[item] else math.inf))
            result = attempt(policy, self.rng.randrange(1, count), self.rng.choice((-40, 0, 40)), False)
            history[policy].append(result)
        candidates = [policy for policy in POLICIES if history[policy]]
        candidate = max(candidates, key=lambda policy: (
            sum(map(reward, history[policy])) / len(history[policy])))
        held_out = {}
        for policy in dict.fromkeys((BASELINE, candidate)):
            held_out[policy] = [attempt(policy, count, offset, True) for offset in (-80, 0, 80)]
        winner = max(held_out, key=lambda policy: rank(held_out[policy]))
        report = dict(seed=self.seed, training_attempts=self.attempts, trial_seconds=self.seconds,
                      winner=asdict(winner), evaluated=[
                          dict(policy=asdict(policy), captures=int(sum(row['capture'] for row in results)),
                               pickups=int(sum(row['pickup'] for row in results)),
                               mean_reward=round(sum(map(reward, results))/len(results), 3),
                               trials=len(results))
                          for policy, results in held_out.items()])
        publish(out / 'evaluation.json', json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--attempts', type=int, default=20)
    parser.add_argument('--seconds', type=int, default=25)
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.attempts <= 50 or not 3 <= args.seconds <= 90:
        parser.error('Use 1–50 attempts and 3–90 seconds per attempt.')
    if not args.smoke and (args.attempts + 6) * (args.seconds + 6) > 850:
        parser.error('Shorten the trials or reduce the attempt count to fit one native match.')
    trainer = Trainer(args.attempts, 5 if args.smoke else args.seconds, args.seed, args.smoke)
    start(json.loads(args.config.read_bytes()), trainer=trainer)
