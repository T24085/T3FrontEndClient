"""The milestone merge driver and the checks that catch a bad milestone merge."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
import merge_milestone_file as driver  # noqa: E402
import project_milestones as pm  # noqa: E402

BASE = """# M2: Flags

- Status: in progress
- Updated: 2026-11-01
- Target: not set

## Goal

Flags behave.

## Done when

- [ ] Flags behave in a played match.

## Issues

- [ ] #52 Flag falls straight down

Closed process issues: #58 and #68 (overnight fix
tracking).

## Progress log

- 2026-11-01: Created.
"""


def edit(text, *pairs):
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


class DriverTest(unittest.TestCase):
    def merge(self, ours, theirs):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder, name) for name in ('base.md', 'ours.md', 'theirs.md')]
            for path, text in zip(paths, (BASE, ours, theirs)):
                path.write_bytes(text.encode('utf-8'))
            code = driver.main(*(str(path) for path in paths))
            return code, paths[1].read_bytes().decode('utf-8')

    def test_both_sides_append_progress_and_issues(self):
        ours = edit(BASE, ('- Updated: 2026-11-01', '- Updated: 2026-11-03'),
                    ('- [ ] #52 Flag falls straight down\n', '- [ ] #52 Flag falls straight down\n- [ ] #60 Ours\n'),
                    ('- 2026-11-01: Created.\n', '- 2026-11-01: Created.\n- 2026-11-03: Ours.\n'))
        theirs = edit(BASE, ('- Updated: 2026-11-01', '- Updated: 2026-11-02'),
                      ('- [ ] #52 Flag falls straight down\n',
                       '- [ ] #52 Flag falls straight down\n- [ ] #61 Theirs\n- [ ] #60 Theirs wording\n'),
                      ('- 2026-11-01: Created.\n', '- 2026-11-01: Created.\n- 2026-11-02: Theirs.\n'))
        code, merged = self.merge(ours, theirs)
        self.assertEqual(code, 0)
        self.assertNotIn('<<<<<<<', merged)
        self.assertIn('- Updated: 2026-11-03\n', merged)
        self.assertEqual(merged.count('- Updated:'), 1)
        self.assertIn('- [ ] #60 Ours\n', merged)
        self.assertNotIn('#60 Theirs wording', merged)
        self.assertIn('- [ ] #61 Theirs\n', merged)
        log = merged.split('## Progress log\n', 1)[1]
        self.assertLess(log.index('2026-11-02: Theirs.'), log.index('2026-11-03: Ours.'))

    def test_the_same_note_wrapped_differently_is_kept_once(self):
        ours = edit(BASE, ('- [ ] #52 Flag falls straight down\n', '- [ ] #52 Flag falls straight down\n- [ ] #60 Ours\n'))
        theirs = edit(BASE, ('Closed process issues: #58 and #68 (overnight fix\ntracking).',
                             '- [ ] #61 Theirs\n\nClosed process issues: #58 and #68\n  (overnight fix tracking).'))
        code, merged = self.merge(ours, theirs)
        self.assertEqual(code, 0)
        self.assertEqual(merged.count('Closed process issues'), 1)

    def test_a_status_disagreement_stays_a_conflict(self):
        ours = edit(BASE, ('- Status: in progress', '- Status: blocked'))
        theirs = edit(BASE, ('- Status: in progress', '- Status: done'))
        code, merged = self.merge(ours, theirs)
        self.assertEqual(code, 1)
        self.assertIn('<<<<<<< ours', merged)


class CheckTest(unittest.TestCase):
    def problems(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'M2-flags.md')
            path.write_bytes(text.encode('utf-8'))
            return pm.problems([pm.parse(path)])

    def test_bad_merges_are_reported(self):
        self.assertEqual(self.problems(BASE), [])
        twice = edit(BASE, ('- Updated: 2026-11-01\n', '- Updated: 2026-11-01\n- Updated: 2026-11-02\n'))
        self.assertIn('M2-flags.md: "- Updated:" appears more than once.', self.problems(twice))
        repeated = edit(BASE, ('- [ ] #52 Flag falls straight down\n',
                               '- [ ] #52 Flag falls straight down\n- [ ] #52 Again\n'))
        self.assertIn('M2-flags.md: #52 is listed more than once.', self.problems(repeated))
        markers = edit(BASE, ('- 2026-11-01: Created.\n', '<<<<<<< ours\n- 2026-11-01: Created.\n'))
        self.assertIn('M2-flags.md: contains unresolved merge conflict markers.', self.problems(markers))


if __name__ == '__main__':
    unittest.main()
