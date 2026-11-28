"""The project milestone files, their helpers, and the commit rules that keep them current."""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
import check_commit_message as ccm  # noqa: E402
import github_issues as gi  # noqa: E402
import project_milestones as pm  # noqa: E402

SAMPLE = """# M2: Flags

- Status: in progress
- Updated: 2026-11-01
- Target: not set

## Goal

Flags behave.

## Done when

- [ ] Flags behave in a played match.

## Issues

- [ ] #52 Flag falls straight down - branch issue-52
- [x] #36 Flag throw goes backwards

## Progress log

- 2026-11-01: Created.
"""

EXPLAINED = """Keep flag momentum when the carrier dies

What: the dropped flag now inherits the carrier's velocity on death.
Why: the flag fell straight down, unlike the original game, which players reported.
Verification: unit tests pass; native gameplay is not verified.
"""


def write(folder, name, text):
    path = Path(folder) / name
    path.write_text(text, encoding='utf-8')
    return path


class RepositoryPlan(unittest.TestCase):
    def test_repository_milestones_are_valid(self):
        milestones = pm.load()
        self.assertTrue(milestones, 'project/milestones has no milestone files')
        self.assertEqual(pm.problems(milestones), [])

    def test_readme_lists_every_milestone(self):
        readme = (ROOT / 'project' / 'README.md').read_text(encoding='utf-8')
        for m in pm.load():
            self.assertIn(f'milestones/{m.path.name}', readme)

    def test_agents_rule_binds_every_harness(self):
        agents = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn('## Keep the project and milestones current', agents)
        for tool in ('Claude Code', 'Cursor', 'Grok', 'Codex'):
            self.assertIn(tool, agents.split('## Keep the project and milestones current')[1])

    def test_workflow_runs_the_tracker_check(self):
        workflow = (ROOT / '.github' / 'workflows' / 'checks.yml').read_text(encoding='utf-8')
        self.assertIn('python tools/project_milestones.py check', workflow)
        self.assertIn('--tracker "$PR_BASE" "$PR_HEAD"', workflow)
        self.assertIn('--tracker origin/main "$AFTER"', workflow)


class Parsing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_parse_fields_and_issues(self):
        m = pm.parse(write(self.dir.name, 'M2-flags.md', SAMPLE))
        self.assertEqual((m.id, m.title, m.status), ('M2', 'Flags', 'in progress'))
        self.assertEqual(m.issues, {52: False, 36: True})

    def test_problems_catch_bad_files(self):
        good = pm.parse(write(self.dir.name, 'M2-flags.md', SAMPLE))
        clash = pm.parse(write(self.dir.name, 'M3-more.md', SAMPLE.replace('M2', 'M3')))
        bad = pm.parse(write(self.dir.name, 'M4-bad.md', SAMPLE.replace('M2', 'M5')
                             .replace('in progress', 'started').replace('2026-11-01\n', 'soon\n', 1)))
        found = '\n'.join(pm.problems([good, clash, bad]))
        self.assertIn('#52 is listed in both M2 and M3', found)
        self.assertIn('file name says M4 but the heading says M5', found)
        self.assertIn('Status must be one of', found)
        self.assertIn('Updated must be a YYYY-MM-DD date', found)

    def test_done_requires_every_issue_ticked(self):
        m = pm.parse(write(self.dir.name, 'M2-flags.md', SAMPLE.replace('in progress', 'done')))
        self.assertIn('marked done but #52 not ticked', '\n'.join(pm.problems([m])))

    def test_missing_folder_means_no_tracker(self):
        self.assertEqual(pm.load(self.dir.name), [])


class Editing(unittest.TestCase):
    TODAY = date(2026, 11, 26)

    def test_log_appends_and_touches_updated(self):
        text = pm.append_log(SAMPLE, 'Fix pushed on issue-52.', self.TODAY)
        self.assertTrue(text.endswith('- 2026-11-26: Fix pushed on issue-52.\n'))
        self.assertIn('- Updated: 2026-11-26', text)

    def test_tick_and_untick_issue(self):
        text = pm.set_issue(SAMPLE, 52, True, self.TODAY)
        self.assertIn('- [x] #52 Flag falls', text)
        self.assertIn('- [ ] #36 Flag throw', pm.set_issue(text, 36, False, self.TODAY))
        with self.assertRaises(SystemExit):
            pm.set_issue(SAMPLE, 99, True, self.TODAY)

    def test_status_must_be_known(self):
        self.assertIn('- Status: blocked', pm.set_status(SAMPLE, 'blocked', self.TODAY))
        with self.assertRaises(SystemExit):
            pm.set_status(SAMPLE, 'paused', self.TODAY)


class Audit(unittest.TestCase):
    def test_reports_disagreements_with_github(self):
        with tempfile.TemporaryDirectory() as folder:
            m = pm.parse(write(folder, 'M2-flags.md', SAMPLE.replace('- [ ] #52', '- [x] #52')
                               .replace('- [x] #36', '- [ ] #36')))
        lines = pm.audit([m], [{'number': 52, 'title': 'x'}, {'number': 77, 'title': 'New bug'}],
                         {36})
        self.assertEqual(lines, ['#52 is ticked in M2 but still open on GitHub.',
                                 '#77 is open but in no milestone: New bug',
                                 '#36 is closed on GitHub but not ticked in M2.'])


class MilestoneTrailer(unittest.TestCase):
    KNOWN = {'M0', 'M2'}

    def test_named_milestone_passes(self):
        self.assertEqual(ccm.problems(EXPLAINED + '\nMilestone: M2\n', self.KNOWN), [])
        self.assertEqual(ccm.problems(EXPLAINED + '\nMilestone: none\n', self.KNOWN), [])
        self.assertEqual(ccm.problems(EXPLAINED + '\nMilestones: m2, M0\n', self.KNOWN), [])

    def test_missing_or_unknown_milestone_is_rejected(self):
        self.assertTrue(any('Milestone: M<n>' in f for f in ccm.problems(EXPLAINED, self.KNOWN)))
        found = ccm.problems(EXPLAINED + '\nMilestone: M9\n', self.KNOWN)
        self.assertTrue(any('Unknown milestone M9' in f for f in found))

    def test_trailer_does_not_count_as_explanation(self):
        message = 'Adjust lobby timeout\n\nShort body.\n\nMilestone: ' + ' '.join(['M2'] * 20)
        self.assertTrue(any('explanation has 2 words' in f
                            for f in ccm.problems(message, self.KNOWN)))

    def test_no_tracker_skips_the_rule(self):
        self.assertEqual(ccm.problems(EXPLAINED, None), [])

    def test_working_tree_ids_match_files(self):
        self.assertEqual(ccm.working_tree_milestones(), pm.ids())

    def test_issue_branch_gets_milestone_trailer(self):
        found = gi.add_milestone_trailer(EXPLAINED, 52, find=lambda n: SimpleNamespace(id='M2'))
        self.assertTrue(found.rstrip().endswith('Milestone: M2'))
        kept = EXPLAINED + '\nMilestone: none\n'
        self.assertEqual(gi.add_milestone_trailer(kept, 52, find=lambda n: SimpleNamespace(id='M2')),
                         kept)
        self.assertEqual(gi.add_milestone_trailer(EXPLAINED, 52, find=lambda n: None), EXPLAINED)


class TrackerRange(unittest.TestCase):
    """--tracker against a throwaway repository."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.repo = Path(self.dir.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'test@example.com')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'core.hooksPath', os.devnull)
        write(self.repo, 'old.txt', 'history from before the rule\n')
        self.commit('Old commit without a milestone')
        self.before_rule = self.head()
        (self.repo / 'project' / 'milestones').mkdir(parents=True)
        write(self.repo / 'project' / 'milestones', 'M2-flags.md', SAMPLE)
        self.commit('Add the tracker', 'Milestone: M0')
        self.base = self.head()
        self.cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.cwd)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def head(self):
        return self.git('rev-parse', 'HEAD')

    def commit(self, subject, trailer=''):
        self.git('add', '-A')
        body = ' '.join(['explanation'] * 16)
        self.git('commit', '-q', '-m', f'{subject}\n\n{body}\n\n{trailer}'.rstrip())

    def test_branch_naming_a_milestone_must_touch_its_file(self):
        write(self.repo, 'code.py', 'x = 1\n')
        self.commit('Change code for flags', 'Milestone: M2')
        self.assertIn('M2', '\n'.join(ccm.tracker_problems(self.base, 'HEAD')))
        path = self.repo / 'project' / 'milestones' / 'M2-flags.md'
        path.write_text(pm.append_log(path.read_text(encoding='utf-8'), 'Fixed.'), encoding='utf-8')
        self.commit('Record flag progress', 'Milestone: M2')
        self.assertEqual(ccm.tracker_problems(self.base, 'HEAD'), [])

    def test_none_and_pre_rule_commits_are_exempt(self):
        write(self.repo, 'typo.txt', 'fixed\n')
        self.commit('Fix a typo in a note', 'Milestone: none')
        self.assertEqual(ccm.tracker_problems(self.base, 'HEAD'), [])
        self.assertIsNone(ccm.commit_milestones(self.before_rule))
        self.assertEqual(ccm.commit_milestones(self.base), {'M2'})

    def test_range_check_requires_trailer_only_after_the_rule(self):
        self.assertEqual(ccm.check_range(f'{self.before_rule}~0'), 0)
        write(self.repo, 'code.py', 'x = 2\n')
        self.commit('Change code without naming a milestone')
        self.assertEqual(ccm.check_range(f'{self.base}..HEAD'), 1)


if __name__ == '__main__':
    unittest.main()
