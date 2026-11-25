"""Compare capper routes against two defenders in local High Octane practice."""
import argparse
from dataclasses import asdict, replace
import json
import msvcrt
from pathlib import Path
from statistics import mean, median
import time

from batch import Campaign, run, select
from practice import HERE
from train import Policy, Trainer, rank, replace_once


class DefenseTrainer(Trainer):
    bot_count = 3
    defense_script = 'defense.lua'

    def instrument(self, text, out):
        text = super().instrument(text, out)
        text = replace_once(text, '  local starts={{},{}}',
                            '  teams={1,2,2}\n  local starts={{},{}}')
        text = replace_once(text, '  local data_path=', f'''
  local role_assets=assert(loadfile({json.dumps((HERE / 'role_assets.lua').as_posix())}))()(valid,report)
  local data_path=''')
        text = replace_once(text, '   engine_valid=engine_valid}', '   engine_valid=engine_valid,role_assets=role_assets}')
        text = replace_once(text, 'SpawnBotFromDataWithTeamId(gm,state.data,team',
                            'SpawnBotFromDataWithTeamId(gm,state.role_assets[#entries+1],team')
        text = replace_once(text, 'assert(#entries==1 and entry.team==1 and entry.pawn and entry.controller',
                            'assert(#entries==3 and entry.team==1 and entry.pawn and entry.controller')
        text = replace_once(text, 'pcall(train,gm,gs,entry.pawn,entry.controller)',
                            'pcall(train,gm,gs,entry.pawn,entry.controller,{entries[2].controller,entries[3].controller})')
        return replace_once(text, 'scope=scope,signature=signature,report=report,valid=valid\n',
            'scope=scope,signature=signature,report=report,valid=valid,\n'
            f"  defense_script={json.dumps((HERE / self.defense_script).as_posix())}\n")


class GroundedDefenseTrainer(DefenseTrainer):
    defense_script = 'defense_grounded.lua'


class BodyBlockTrainer(GroundedDefenseTrainer):
    def instrument(self, text, out):
        text = super().instrument(text, out)
        text = replace_once(text, "  local data_path=", f"""
  local prepareJuggernaut=assert(loadfile({json.dumps((HERE / 'juggernaut.lua').as_posix())}))()
  local finishJuggernaut=prepareJuggernaut(role_assets[2],valid,report,signature)
  local data_path=""")
        text = replace_once(text, 'engine_valid=engine_valid,role_assets=role_assets}',
                            'engine_valid=engine_valid,role_assets=role_assets,finishJuggernaut=finishJuggernaut}')
        text = replace_once(text, "   local entry=assert(entries[1])",
                            "   state.finishJuggernaut(entries[2].pawn)\n   local entry=assert(entries[1])")
        return replace_once(text, '  defense_script=', '  body_block=true,defense_script=')


class DefenseCampaign(Campaign):
    def __init__(self, output, attempts, seed, grounded=False, prior=None, scenario=None):
        self.grounded = grounded
        super().__init__(output, attempts, 76, seed, prior=prior,
                         scenario=scenario or ('grounded-defense' if grounded else None))

    def make_trainer(self):
        trainer = GroundedDefenseTrainer if self.grounded else DefenseTrainer
        return trainer(0, self.seconds, self.seed, False, batch=self.play)

    def report_fields(self):
        def group(rows):
            keys = ('hof_alive_seconds', 'ld_alive_seconds', 'hof_near_flag_seconds',
                    'ld_near_carrier_seconds', 'damage_taken')
            return dict(
                attempts=len(rows),
                flag_grabs_denied=sum(not row['pickup'] for row in rows),
                captures_denied=sum(not row['capture'] for row in rows),
                capper_deaths=sum(bool(row['defense']['died']) for row in rows),
                light_defense_contacts=sum(row['defense']['ld_near_carrier_seconds'] > 0 for row in rows),
                **{f'median_{key}': round(median(row['defense'][key] for row in rows), 2) if rows else None
                   for key in keys},
            )

        return {'defense': group(self.rows), 'defense_evaluation': {
            role: group([row for row in self.rows if row['evaluation_role'] == role])
            for role in ('baseline', 'selected')
        }}


class RefinedDefenseCampaign(DefenseCampaign):
    held_out_starts = ((1, 100), (2, -100), (3, -100), (3, 40), (3, 100))

    def __init__(self, output, attempts, seed, prior):
        if (prior['configuration'].get('scenario') != 'grounded-defense'
                or prior['completed'] != prior['configuration']['attempts']):
            raise ValueError('Refinement needs a completed grounded-defense checkpoint.')
        super().__init__(output, attempts, seed, grounded=True, prior=prior)

    def candidates(self, baseline):
        return (baseline,
                *(replace(baseline, approach_cm=distance) for distance in (2000, 2100, 2300, 2400)),
                *(replace(baseline, turn=turn) for turn in (-4, 0)),
                replace(baseline, pulse=.30))


def defender_reward(row):
    stopped = not row['capture']
    damage = min(row['defense']['damage_taken'] / 1000, 1.0)
    return (4 * stopped + 2 * (not row['pickup']) + row['defense']['died']
            + (row['seconds'] / 76 if not stopped else 0) + damage)


class DefenderLearningCampaign(DefenseCampaign):
    held_out_starts = ((1, -100), (2, 100), (3, -60), (3, 60), (3, 90))

    def __init__(self, output, attempts, seed, prior, body_block=False):
        if (prior['configuration'].get('scenario') != 'grounded-defense'
                or prior['completed'] != prior['configuration']['attempts']):
            raise ValueError('Defender training needs a completed grounded-defense checkpoint.')
        groups = {role: [row for row in prior['attempts'] if row['evaluation_role'] == role]
                  for role in ('baseline', 'selected')}
        if not groups['baseline'] or len(groups['baseline']) != len(groups['selected']):
            raise ValueError('Defender training needs a complete matched capper evaluation.')
        winner = max(groups, key=lambda role: rank(groups[role]))
        self.capper = Policy(**groups[winner][0]['policy'])
        self.body_block = body_block
        super().__init__(output, attempts, seed, grounded=True,
                         scenario='juggernaut-body-block-v1' if body_block else 'defender-learning-v1')

    def make_trainer(self):
        if self.body_block:
            return BodyBlockTrainer(0, self.seconds, self.seed, False, batch=self.play)
        return super().make_trainer()

    def policy_configuration(self):
        self.baseline = 1
        self.policies = tuple(range(1, 9))
        return dict(defense_profiles=list(self.policies), capper_policy=asdict(self.capper))

    def played_policy(self, row):
        return row['defense_profile']

    def select_policy(self, history, rng):
        return select(history, rng, self.baseline, score=defender_reward)

    def evaluation_policy(self, history):
        eligible = [profile for profile, rows in history.items() if len(rows) >= 3]
        return max(eligible or [self.baseline],
                   key=lambda profile: mean(map(defender_reward, history[profile])))

    def play_attempt(self, attempt, policy, spawn, offset, evaluating):
        row = attempt(self.capper, spawn, offset, evaluating, defense_profile=policy)
        return dict(row, defense_profile=policy, defender_reward=defender_reward(row))

    def evaluation_settings(self, row):
        return dict(policy=row['policy'], defense_profile=row['defense_profile'])


def wait_for_predecessor(checkpoint):
    campaign_lock = checkpoint.with_name('campaign.lock')
    print(f'Waiting for the first batch to release {campaign_lock.parent}', flush=True)
    with campaign_lock.open('r+b') as lock:
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno != 13:
                    raise
                time.sleep(15)
        prior = json.loads(checkpoint.read_bytes())
        if prior['completed'] != prior['configuration']['attempts']:
            print(f"First batch stopped at {prior['completed']}/{prior['configuration']['attempts']}. "
                  "Continuing with the independent follow-up batch.", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--attempts', type=int, default=25)
    parser.add_argument('--refine-from', type=Path, help='Start with the winner of a completed grounded-defense batch.')
    parser.add_argument('--train-defense-against', type=Path, help='Train defender profiles against the last matched capper winner.')
    parser.add_argument('--juggernaut-block', action='store_true', help='Use Juggernaut armor and lane blocking in defender training.')
    parser.add_argument('--grounded', action='store_true', help='Use verified floor anchors and role-based pursuit.')
    parser.add_argument('--wait-for', type=Path, help='Wait for the preceding campaign process to release its lock.')
    args = parser.parse_args()
    if not 1 <= args.attempts <= 100:
        parser.error('Use 1–100 attempts.')
    if args.refine_from and args.train_defense_against:
        parser.error('Select either capper refinement or defender training.')
    if args.juggernaut_block and not args.train_defense_against:
        parser.error('Juggernaut blocking requires defender training.')
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'campaign.lock').open('a+b') as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        if args.train_defense_against:
            if args.attempts < 12:
                parser.error('Use at least 12 attempts for defender training.')
            prior = json.loads(args.train_defense_against.read_bytes())
            campaign = DefenderLearningCampaign(args.output, args.attempts, 2026, prior,
                                               body_block=args.juggernaut_block)
        elif args.refine_from:
            prior = json.loads(args.refine_from.read_bytes())
            campaign = RefinedDefenseCampaign(args.output, args.attempts, 2026, prior)
        else:
            campaign = DefenseCampaign(args.output, args.attempts, 2026, grounded=args.grounded)
        campaign.write()
        if args.wait_for:
            if args.wait_for.parent.resolve() == args.output.resolve():
                parser.error('The predecessor and follow-up need separate directories.')
            wait_for_predecessor(args.wait_for)
        run(json.loads(args.config.read_bytes()), campaign)
