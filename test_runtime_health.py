import unittest
from runtime_health import runtime_failure


class RuntimeHealthTest(unittest.TestCase):
    def test_module_faults_are_fatal_but_names_and_embedded_text_are_not(self):
        for event in ('ENERGY_RECHARGE_ERROR|failed','JETPACK_INPUT_ERROR|failed',
                      'FLAG_MARKER_ERROR|failed','PAWN_LIFECYCLE_ERROR|failed',
                      'SELF_DAMAGE_ERROR|failed','PROJECTILE_LISTEN_COMPAT_ERROR|failed',
                      'TURRET_RECOVERY_ERROR|failed',
                      'RUNTIME_ERROR|failed','ERROR first-line'):
            with self.subTest(event=event):
                self.assertEqual(runtime_failure(('READY',event)),event)
                self.assertIsNone(runtime_failure(('PLAYER_NAME|'+event,)))
        self.assertIsNone(runtime_failure(('ENERGY_RECHARGE_READY','FLAG_MARKERS_READY')))


if __name__=='__main__': unittest.main()
