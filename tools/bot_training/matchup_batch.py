"""Compare capper routes and Juggernaut defense on matched native starts."""
import argparse
from dataclasses import asdict, replace
import json
import msvcrt
from pathlib import Path
import random
from statistics import mean

from batch import run
from defense_batch import BodyBlockTrainer, DefenseCampaign, defender_reward
from train import Policy, rank, summarize


TRAINING_STARTS = ((1, -40), (2, 0), (3, 40))
EVALUATION_STARTS = tuple((spawn, offset) for spawn in (1, 2, 3)
                          for offset in (-95, -65, 65, 95))
BASELINE_DEFENSE = 4
DEFENSE_PROFILES = (BASELINE_DEFENSE, 1, 3, 6)


class MatchupCampaign(DefenseCampaign):
    held_out_starts = EVALUATION_STARTS

    def __init__(self, output, prior, seed=2026):
        if (prior['configuration'].get('scenario') != 'juggernaut-body-block-v1'
                or prior['completed'] != prior['configuration']['attempts']
                or prior['evaluation']['selected']['defense_profile'] != BASELINE_DEFENSE):
            raise ValueError('Use the completed Juggernaut checkpoint with defense profile 4.')
        self.capper = Policy(**prior['configuration']['capper_policy'])
        self.routes = (
            self.capper, replace(self.capper, approach_cm=2000),
            replace(self.capper, pulse=.40, period=2.2),
            replace(self.capper, flank=1), replace(self.capper, flank=-1),
            replace(self.capper, flank=2), replace(self.capper, flank=-2),
            replace(self.capper, flank=1, pulse=.40, period=2.2),
        )
        self.training_plan = []
        for spawn, offset in TRAINING_STARTS:
            matches = [(route, defense) for route in range(len(self.routes)) for defense in DEFENSE_PROFILES]
            random.Random(f'{seed}:matchups:{spawn}:{offset}').shuffle(matches)
            self.training_plan.extend((match, spawn, offset, None) for match in matches)
        super().__init__(output, len(self.training_plan) + 4 * len(EVALUATION_STARTS), seed,
                         grounded=True, scenario='juggernaut-matched-tournament-v1')
        self.training_total = len(self.training_plan)

    def policy_configuration(self):
        self.baseline = (0, BASELINE_DEFENSE)
        self.policies = tuple((route, defense) for route in range(len(self.routes)) for defense in DEFENSE_PROFILES)
        return dict(capper_routes=[asdict(route) for route in self.routes],
                    defense_profiles=list(DEFENSE_PROFILES),
                    training_starts=[list(start) for start in TRAINING_STARTS],
                    training_attempts=len(self.training_plan),
                    baseline_defense=BASELINE_DEFENSE)

    def make_trainer(self):
        return BodyBlockTrainer(0, self.seconds, self.seed, False, batch=self.play)

    def played_policy(self, row):
        return row['capper_route'], row['defense_profile']

    def winners(self, rows):
        capper = max(range(len(self.routes)), key=lambda route: rank(
            [row for row in rows if row['capper_route'] == route]))
        defender = max(DEFENSE_PROFILES, key=lambda profile: (
            sum(not row['capture'] for row in rows if row['defense_profile'] == profile),
            mean(defender_reward(row) for row in rows if row['defense_profile'] == profile),
        ))
        return capper, defender

    def trial_plan(self, index, history, rng):
        if index < self.training_total:
            return self.training_plan[index]
        capper, defender = self.winners([row for rows in history.values() for row in rows])
        start, position = divmod(index - self.training_total, 4)
        spawn, offset = self.held_out_starts[start]
        combinations = (
            ((0, BASELINE_DEFENSE), 'baseline_capper_baseline_defense'),
            ((capper, BASELINE_DEFENSE), 'selected_capper_baseline_defense'),
            ((0, defender), 'baseline_capper_selected_defense'),
            ((capper, defender), 'selected_capper_selected_defense'),
        )
        # Rotate order so each pairing occupies each slot equally often.
        policy, role = combinations[(position + start) % 4]
        return policy, spawn, offset, role

    def play_attempt(self, attempt, policy, spawn, offset, evaluating):
        route, defense = policy
        row = attempt(self.routes[route], spawn, offset, evaluating, defense_profile=defense)
        return dict(row, capper_route=route, defense_profile=defense,
                    defender_reward=defender_reward(row))

    def evaluation_settings(self, row):
        return dict(policy=row['policy'], capper_route=row['capper_route'], defense_profile=row['defense_profile'])

    def report_fields(self):
        training = [row for row in self.rows if not row['held_out']]
        capper, defender = self.winners(training) if len(training) == self.training_total else (None, None)
        groups = {}
        for row in self.rows:
            if row['held_out']:
                groups.setdefault(row['evaluation_role'], []).append(row)
        return dict(
            selected_capper_route=capper, selected_defense_profile=defender,
            route_training={
                i: summarize([row for row in training if row['capper_route'] == i])
                for i in range(len(self.routes))
            },
            defense_training={
                profile: self.defense_summary([row for row in training if row['defense_profile'] == profile])
                for profile in DEFENSE_PROFILES
            },
            paired_defense={role: self.defense_summary(rows) for role, rows in groups.items()},
        )

    @staticmethod
    def defense_summary(rows):
        return dict(attempts=len(rows), captures_denied=sum(not row['capture'] for row in rows),
                    grabs_denied=sum(not row['pickup'] for row in rows),
                    capper_deaths=sum(bool(row['defense']['died']) for row in rows),
                    average_damage=round(mean(row['defense']['damage_taken'] for row in rows), 1) if rows else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('prior', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'campaign.lock').open('a+b') as lock:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        campaign = MatchupCampaign(args.output, json.loads(args.prior.read_bytes()))
        run(json.loads(args.config.read_bytes()), campaign)


if __name__ == '__main__':
    main()
