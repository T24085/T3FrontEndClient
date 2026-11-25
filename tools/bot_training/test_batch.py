from pathlib import Path
from tempfile import TemporaryDirectory
import json
from collections import Counter
import unittest

from batch import Campaign, FASTER_APPROACH, HELD_OUT
from defense_batch import DefenseCampaign, DefenderLearningCampaign, RefinedDefenseCampaign, defender_reward
from matchup_batch import BASELINE_DEFENSE, MatchupCampaign
from paired_flag_screen import screening_score, stand_speed_score


class CampaignTest(unittest.TestCase):
    def test_stand_speed_progress_earns_credit_before_and_after_100(self):
        self.assertEqual(stand_speed_score(0), 0)
        for speed in (20, 40, 60, 80):
            self.assertAlmostEqual(stand_speed_score(speed + 10) - stand_speed_score(speed), 0.4)
        self.assertAlmostEqual(stand_speed_score(100) - stand_speed_score(99), 0.04)
        self.assertGreater(stand_speed_score(110), stand_speed_score(100))
        self.assertEqual(screening_score(dict(contact=False, pass_speed_kmh=120)), 0)
        self.assertGreater(screening_score(dict(contact=True, contact_kmh=80)),
                           screening_score(dict(contact=True, contact_kmh=60)))

    def test_matchup_schedule_balances_routes_profiles_and_held_out_starts(self):
        with TemporaryDirectory() as directory:
            prior = dict(configuration=dict(attempts=61, scenario='juggernaut-body-block-v1',
                                            capper_policy=FASTER_APPROACH.__dict__),
                         completed=61, evaluation=dict(selected=dict(defense_profile=BASELINE_DEFENSE)))
            campaign = MatchupCampaign(Path(directory), prior)
            self.assertEqual((campaign.training_total, campaign.total), (96, 144))
            self.assertEqual(set(Counter(policy for policy, *_ in campaign.training_plan).values()), {3})
            rows = [dict(capper_route=route, defense_profile=defense, capture=int(route == 1 and defense != 3),
                         pickup=1, seconds=50, closest_cm=20, initial_cm=100,
                         defense=dict(died=0, damage_taken=0)) for route, defense in campaign.policies]
            self.assertEqual(campaign.winners(rows), (1, 3))
            history = {policy: [row] for policy, row in zip(campaign.policies, rows, strict=True)}
            validation = [campaign.trial_plan(i, history, None) for i in range(96, 144)]
            self.assertEqual(set(Counter(role for *_, role in validation).values()), {12})
            for index in range(0, 48, 4):
                self.assertEqual(len({(s, o) for _, s, o, _ in validation[index:index+4]}), 1)

    def test_defender_learning_keeps_capper_fixed_and_prefers_stops(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            capper = dict(FASTER_APPROACH.__dict__, approach_cm=2200, turn=0)
            result = dict(pickup=1, capture=1, initial_cm=50000, closest_cm=100)
            prior = dict(configuration=dict(attempts=50, scenario='grounded-defense'), completed=50,
                         attempts=[
                             dict(result, evaluation_role='baseline', policy=FASTER_APPROACH.__dict__, seconds=47),
                             dict(result, evaluation_role='selected', policy=capper, seconds=44),
                         ])
            campaign = DefenderLearningCampaign(root, 100, 2026, prior)
            self.assertEqual(campaign.training_total, 90)
            self.assertEqual(campaign.capper.__dict__, capper)
            def attempt(policy, spawn, offset, evaluating, defense_profile):
                self.assertEqual(policy.__dict__, capper)
                self.assertEqual(defense_profile, 2)
                return dict(result, seconds=76, capture=0, defense=dict(died=0, damage_taken=0))
            stop = campaign.play_attempt(attempt, 2, 1, 0, False)
            late_cap = dict(stop, capture=1, defense=dict(died=0, damage_taken=999))
            self.assertGreater(defender_reward(stop), defender_reward(late_cap))
            self.assertEqual(campaign.evaluation_policy({1: [late_cap]*3, 2: [stop]*3}), 2)

    def test_refinement_uses_previous_winner_and_fresh_evaluation_starts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            faster = dict(FASTER_APPROACH.__dict__, approach_cm=2200)
            result = dict(pickup=1, capture=1, initial_cm=50000, closest_cm=100)
            prior = dict(configuration=dict(attempts=25, scenario='grounded-defense'), completed=25,
                         attempts=[
                             dict(result, held_out=True, evaluation_role='baseline',
                                  policy=FASTER_APPROACH.__dict__, seconds=54),
                             dict(result, held_out=True, evaluation_role='selected', policy=faster, seconds=48),
                         ])
            campaign = RefinedDefenseCampaign(root, 50, 2026, prior)
            self.assertEqual(campaign.baseline.__dict__, faster)
            self.assertEqual(campaign.training_total, 40)
            self.assertEqual(len(set(campaign.policies)), 8)
            self.assertTrue(set(campaign.held_out_starts).isdisjoint(HELD_OUT))
            campaign.write()
            self.assertEqual(RefinedDefenseCampaign(root, 50, 2026, prior).spec, campaign.spec)

    def test_defender_loss_restarts_match_without_losing_checkpoint(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = DefenseCampaign(root, 25, 2026, grounded=True)

            def attempt(policy, spawn, offset, evaluating):
                return dict(policy=policy.__dict__, held_out=evaluating, capture=0, pickup=0,
                            seconds=76, ski_frames=1, jet_frames=1, initial_cm=50000, closest_cm=100,
                            trace='trace-1.csv', defense=dict(died=0, damage_taken=0, red_caps=0,
                                                            hof_alive_seconds=76, ld_alive_seconds=15,
                                                            hof_near_flag_seconds=70, ld_near_carrier_seconds=2))

            campaign.play(root, 3, attempt)
            self.assertEqual(len(campaign.rows), 1)
            self.assertEqual(DefenseCampaign(root, 25, 2026, grounded=True).rows, campaign.rows)
            report = json.loads(campaign.checkpoint.read_bytes())
            self.assertEqual(report['configuration']['scenario'], 'grounded-defense')
            self.assertEqual(report['defense']['light_defense_contacts'], 1)
            self.assertEqual(report['defense']['median_hof_near_flag_seconds'], 70)

    def test_resume_keeps_count_and_uses_matched_held_out_pairs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            campaign = Campaign(root, 12, 76, 2026)

            def attempt(policy, spawn, offset, evaluating):
                return dict(policy=policy.__dict__, spawn=spawn, offset_cm=offset, held_out=evaluating,
                            capture=1, pickup=1, seconds=50, pickup_seconds=24, ski_frames=1, jet_frames=1,
                            initial_cm=50000, closest_cm=100, closest_home_cm=200, trace='trace-1.csv')

            campaign.play(root, 3, attempt)
            self.assertEqual(len(campaign.rows), 5)
            resumed = Campaign(root, 12, 76, 2026)
            self.assertEqual(resumed.rows, campaign.rows)
            resumed.play(root, 3, attempt)
            resumed.play(root, 3, attempt)
            self.assertEqual([row['campaign_attempt'] for row in resumed.rows], list(range(1, 13)))
            for left, right in zip(resumed.rows[8::2], resumed.rows[9::2], strict=True):
                self.assertEqual((left['spawn'], left['offset_cm']), (right['spawn'], right['offset_cm']))
                self.assertEqual((left['evaluation_role'], right['evaluation_role']), ('baseline', 'selected'))
                self.assertEqual(left['policy'], FASTER_APPROACH.__dict__)
                self.assertNotIn(left['offset_cm'], (-40, 0, 40))


if __name__ == '__main__':
    unittest.main()
