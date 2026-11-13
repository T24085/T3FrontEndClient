from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from batch import Campaign, FASTER_APPROACH


class CampaignTest(unittest.TestCase):
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
