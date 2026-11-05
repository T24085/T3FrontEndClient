import unittest

from player_names import display_name


class PlayerNameTest(unittest.TestCase):
    def test_preserves_steam_unicode_spacing_and_emoji_sequences(self):
        for name in ('PandaMonium','  Píløt  ','👨‍👩‍👦 Pilot','🚀'*32,'";error(1)--'):
            with self.subTest(name=name): self.assertEqual(display_name(name),name)

    def test_rejects_oversize_invalid_encoding_and_line_controls(self):
        for name in (None,'','   ','a'*129,'🚀'*33,'Pilot\nOther','\0Pilot','\ud800','Pilot\u2028Other'):
            with self.subTest(name=repr(name)),self.assertRaises(ValueError): display_name(name)


if __name__=='__main__': unittest.main()
