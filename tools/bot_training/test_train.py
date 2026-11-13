import unittest

from train import rank, reward


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


if __name__ == '__main__':
    unittest.main()
