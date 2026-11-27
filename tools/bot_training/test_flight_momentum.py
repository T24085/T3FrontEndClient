import unittest

from flight_momentum import momentum, sustained_score


class FlightMomentumTest(unittest.TestCase):
    def test_fast_glide_and_landing_reward_progress_and_energy(self):
        frames = [
            (0, 60, True, True, 80, 0),
            (.25, 60, True, False, 70, 4),
            (.5, 60, True, False, 65, 8),
            (.75, 54, False, False, 60, 12),
        ]
        result = momentum(frames, .35)
        self.assertEqual(result['fast_air_forward_m'], 8)
        self.assertEqual(result['longest_fast_air_seconds'], .5)
        self.assertEqual(result['fast_glide_seconds'], .25)
        self.assertEqual(result['landing_speed_retained'], .9)
        self.assertEqual(result['landing_energy'], 60)
        drained = result | {'landing_energy': 0}
        self.assertGreater(sustained_score(12, 160, result), sustained_score(12, 160, drained))

    def test_slow_and_discontinuous_air_does_not_extend_fast_flight(self):
        frames = [
            (0, 80, True, True, 80, 0),
            (.25, 60, True, False, 70, 4),
            (2, 60, True, False, 65, 8),
            (2.25, 60, True, False, 65, 12),
            (2.5, 10, True, False, 65, 13),
        ]
        result = momentum(frames, .35)
        self.assertEqual(result['fast_air_seconds'], .5)
        self.assertEqual(result['longest_fast_air_seconds'], .25)
        self.assertIsNone(result['landing_energy'])
