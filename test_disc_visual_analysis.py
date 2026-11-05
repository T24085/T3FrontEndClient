import unittest
from tools.analyze_disc_visual import ahead,vector


class DiscVisualAnalysisTests(unittest.TestCase):
    def test_rotated_camera_does_not_use_world_x_as_forward(self):
        self.assertAlmostEqual(ahead('500,-20,0','0,0,0','0,90,0'),-20)
        self.assertAlmostEqual(ahead('-50,0,0','0,0,0','0,180,0'),50)

    def test_pitch_and_camera_translation_change_forward_distance(self):
        self.assertAlmostEqual(ahead('10,20,80','10,20,30','90,0,0'),50)

    def test_malformed_or_nonfinite_pose_cannot_qualify(self):
        for text in ('1,2','1,2,3,4','nan,0,0','inf,0,0'):
            with self.subTest(text=text),self.assertRaises(ValueError):vector(text)


if __name__=='__main__':unittest.main()
