import unittest

from train import rank, reward, summarize


def trial(*, capture=0, pickup=0, seconds=25, closest=500):
    return dict(capture=capture, pickup=pickup, seconds=seconds, initial_cm=1000, closest_cm=closest)


class TrainingRankTest(unittest.TestCase):
    def test_pickup_outweighs_distance_and_capture_outweighs_pickup(self):
        close = trial(closest=5)
        picked_up = trial(pickup=1)
        captured = trial(capture=1, pickup=1)
        self.assertGreater(reward(picked_up), reward(close))
        self.assertGreater(reward(captured), reward(picked_up))

    def test_held_out_completion_count_wins_before_speed(self):
        fast = trial(capture=1, pickup=1, seconds=8)
        slow = trial(capture=1, pickup=1, seconds=20)
        self.assertGreater(rank([slow, slow]), rank([fast, trial()]))
        self.assertGreater(rank([fast]), rank([slow]))

    def test_grab_and_return_times_are_reported_separately(self):
        first = dict(trial(capture=1, pickup=1, seconds=35), pickup_seconds=15, ski_frames=3, jet_frames=4,
                     average_kmh=120, peak_kmh=190, outbound_average_kmh=125, return_average_kmh=116)
        second = dict(trial(pickup=1), pickup_seconds=17, ski_frames=3, jet_frames=0,
                      average_kmh=100, peak_kmh=210, outbound_average_kmh=118, return_average_kmh=-1)
        summary = summarize([first, second])
        self.assertEqual(summary['median_grab_seconds'], 16)
        self.assertEqual(summary['median_return_seconds'], 20)
        self.assertEqual(summary['median_cap_seconds'], 35)
        self.assertEqual((summary['skiing'], summary['jetting']), (2, 1))
        self.assertEqual(summary['average_kmh'], 110)
        self.assertEqual(summary['peak_kmh'], 210)
        self.assertEqual(summary['outbound_average_kmh'], 121.5)
        self.assertEqual(summary['return_average_kmh'], 116)

    def test_fastest_grab_and_cap_can_be_different_runs(self):
        common = dict(ski_frames=1, jet_frames=1, grab_homeward_kmh=90)
        first = dict(trial(capture=1, pickup=1, seconds=52), **common, id=1, pickup_seconds=28)
        second = dict(trial(capture=1, pickup=1, seconds=56), **common, id=2, pickup_seconds=25)
        result = summarize([first, second])
        self.assertEqual(result['fastest_grab']['id'], 2)
        self.assertEqual(result['fastest_cap']['id'], 1)
        self.assertEqual(result['fastest_cap']['grab_homeward_kmh'], 90)


if __name__ == '__main__':
    unittest.main()
