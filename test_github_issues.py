"""Issue review summary and automatic commit-to-issue linking, without network access."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
import github_issues as gi  # noqa: E402

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def issue(number, title, updated='2026-11-23T00:00:00Z', labels=(), assignees=(), comments=0):
    return {'number': number, 'title': title, 'createdAt': '2026-11-20T00:00:00Z',
            'updatedAt': updated, 'labels': [{'name': n} for n in labels],
            'assignees': [{'login': a} for a in assignees], 'comments': [{}] * comments,
            'url': f'https://github.com/x/y/issues/{number}'}


class BranchToIssue(unittest.TestCase):
    def test_issue_branch_names(self):
        for branch, number in (('issue-49-turret-moves', 49), ('fix/49-turrets', 49),
                               ('gh-7', 7), ('issue49_turrets', 49), ('feature/issue-12-x', 12)):
            with self.subTest(branch=branch):
                self.assertEqual(gi.issue_from_branch(branch), number)

    def test_other_branch_names(self):
        for branch in ('main', 'chore/require-change-explanations', 'nemesis-branch-1', 'HEAD'):
            with self.subTest(branch=branch):
                self.assertIsNone(gi.issue_from_branch(branch))


class Classification(unittest.TestCase):
    def test_groups(self):
        cases = {
            'URGENT: host moves base turrets every time a player spawns': 'Urgent and security',
            "Security sweep: make sure connected clients' info can't leak": 'Urgent and security',
            'Bug: invisible solid object left at player spawn points': 'Bugs',
            'Turrets acquire targets too late, sometimes not until they\'re shot': 'Bugs',
            'Feature request (host + client): lobby settings for score limit': 'Features and proposals',
            "Map update: wire minimap to sensor state where it doesn't go offline": 'Features and proposals',
            'Match restart method (formalise the informal restart after a crash)': 'Other',
        }
        for title, group in cases.items():
            with self.subTest(title=title):
                self.assertEqual(gi.classify(issue(1, title)), group)

    def test_labels_win_over_title(self):
        self.assertEqual(gi.classify(issue(1, 'Tidy lobby text', labels=['bug'])), 'Bugs')


class Review(unittest.TestCase):
    def test_summary_counts_and_markers(self):
        text = gi.render_review([
            issue(49, 'URGENT: turrets move', labels=['in progress'], assignees=['me'], comments=2),
            issue(37, 'Feature request (host + client): lobby settings', updated='2026-11-01T00:00:00Z'),
        ], now=NOW, repo='x/y')
        self.assertIn('2 open | 1 in progress | 1 unassigned | 1 without updates for 14+ days', text)
        self.assertIn('#49 URGENT: turrets move [IN PROGRESS]', text)
        self.assertIn('2 comment(s), @me', text)
        self.assertIn('[needs both repos]', text)
        self.assertLess(text.index('Urgent and security'), text.index('Features and proposals'))

    def test_no_issues(self):
        self.assertEqual(gi.render_review([], now=NOW, repo='x/y'), 'No open issues in x/y.')


class CommitTrailer(unittest.TestCase):
    def test_adds_trailer_once(self):
        message = 'Stop turrets moving\n\nWhat: explains the change in enough words.\n'
        linked = gi.add_issue_trailer(message, 49)
        self.assertTrue(linked.rstrip().endswith('Refs: #49'))
        self.assertEqual(gi.add_issue_trailer(linked, 49), linked)

    def test_existing_mention_is_left_alone(self):
        message = 'Stop turrets moving (#49)\n\nWhat: explains it.\n'
        self.assertEqual(gi.add_issue_trailer(message, 49), message)

    def test_other_issue_numbers_do_not_count(self):
        self.assertIn('Refs: #4', gi.add_issue_trailer('Fix #49 typo\n\nBody text.\n', 4))


if __name__ == '__main__':
    unittest.main()
