"""Reject missing motion and mismatched native measurements in audit reports."""
import tempfile,unittest
from pathlib import Path
from tools.analyze_disc_speed import analyze


class DiscSpeedAnalysisTests(unittest.TestCase):
    def events(self,role,*,moving=True,inheritance=True,trajectory=True):
        lines=[f'DISC_SPEED_DEFAULTS|role={role}|initial=13500|max=27000|forward=1|lateral=0']
        shots=[(13500,'0,0,0')]*3
        shots+=[(18500 if inheritance and moving else 13500,'5000,0,0'if moving else'0,0,0'),(13500,'0,5000,0'if moving else'0,0,0')]
        for i,(speed,source)in enumerate(shots):
            lines.append(f'DISC_SPEED_PROJECTILE|role={role}|id=shot{i}|initial=13500|max=27000|gravity=0|velocity={speed},0,0|sourceVelocity={source}')
            for stamp in (0.05,0.1):lines.append(f'DISC_SPEED_SAMPLE|role={role}|id=shot{i}|dt={stamp}|distanceSpeed={speed if trajectory else 10000}|velocity={speed},0,0')
        return '\n'.join(lines)

    def run_case(self,**options):
        with tempfile.TemporaryDirectory()as folder:
            paths=[Path(folder)/name for name in ('client.txt','server.txt')]
            for path,role in zip(paths,('client','host')):path.write_text(self.events(role,**options))
            return analyze(*paths)

    def test_original_speed_and_directional_inheritance_match(self):
        result=self.run_case();self.assertTrue(result['passed'])
        self.assertEqual(result['roles']['client']['shots'][3]['speed_m_per_s'],185)

    def test_stationary_only_run_cannot_establish_moving_parity(self):
        self.assertFalse(self.run_case(moving=False)['passed'])

    def test_missing_forward_inheritance_fails(self):
        self.assertFalse(self.run_case(inheritance=False)['passed'])

    def test_launch_metadata_cannot_hide_wrong_travel_speed(self):
        self.assertFalse(self.run_case(trajectory=False)['passed'])

    def test_swapped_role_evidence_rejected(self):
        with tempfile.TemporaryDirectory()as folder:
            path=Path(folder)/'events.txt';path.write_text(self.events('client'))
            with self.assertRaisesRegex(ValueError,'role'):analyze(path,path)

    def test_stationary_stopping_samples_do_not_qualify_airborne_travel(self):
        with tempfile.TemporaryDirectory()as folder:
            paths=[Path(folder)/name for name in ('client.txt','server.txt')]
            for path,role in zip(paths,('client','host')):
                lines=self.events(role).splitlines()
                lines=[line.replace('distanceSpeed=13500','distanceSpeed=30000').replace('velocity=13500,0,0','velocity=0,0,0')if line.startswith('DISC_SPEED_SAMPLE')and'id=shot0|'in line else line for line in lines]
                path.write_text('\n'.join(lines))
            result=analyze(*paths);self.assertTrue(result['passed'])
            self.assertEqual(result['roles']['host']['airborne_trajectory_samples'],4)

    def test_missing_airborne_travel_samples_fail(self):
        with tempfile.TemporaryDirectory()as folder:
            paths=[Path(folder)/name for name in ('client.txt','server.txt')]
            for path,role in zip(paths,('client','host')):
                lines=self.events(role).splitlines()
                path.write_text('\n'.join(line for line in lines if not(line.startswith('DISC_SPEED_SAMPLE')and('id=shot3|'in line or'id=shot4|'in line))))
            self.assertFalse(analyze(*paths)['passed'])


if __name__=='__main__':unittest.main()
