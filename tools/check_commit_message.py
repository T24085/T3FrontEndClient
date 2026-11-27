"""Reject commits whose message does not explain the change.

Every commit needs a short subject line, a body that says what changed and why,
and a "Milestone:" trailer naming the project milestone it advances (an ID from
project/milestones, or "none"). The same rules run in three places:

* locally, from .githooks/commit-msg (install with tools/install_git_hooks.py);
* for coding agents, guarded by tools/agent_commit_guard.py (Claude Code and Cursor);
* in CI, against every commit a push or pull request adds (--range).

Usage:
  python tools/check_commit_message.py MESSAGE_FILE
  python tools/check_commit_message.py --range BASE..HEAD
  python tools/check_commit_message.py --new-branch SHA BRANCH
  python tools/check_commit_message.py --tracker BASE HEAD
      Fail when commits in BASE..HEAD name a milestone whose file under
      project/milestones the branch never changed.

The milestone rules apply only to commits whose tree already contains
project/milestones, so history from before the rule is not rejected.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

MAX_SUBJECT = 72
MIN_BODY_WORDS = 15
SCISSORS = '# ------------------------ >8 ------------------------'
TRAILER = re.compile(
    r'^(co-authored-by|signed-off-by|reviewed-by|acked-by|tested-by|reported-by|'
    r'helped-by|suggested-by|refs?|fixes|closes|change-id|milestones?)\s*:', re.IGNORECASE)
MILESTONE_TRAILER = re.compile(r'^milestones?\s*:(.*)$', re.IGNORECASE)
MILESTONE_TOKEN = re.compile(r'\b(M\d+|none)\b', re.IGNORECASE)
MILESTONE_FILE = re.compile(r'^(M\d+)-[^/]*\.md$')
TRACKER = 'project/milestones'
ROOT = Path(__file__).resolve().parents[1]
CHERRY_PICK = re.compile(r'^\(cherry picked from commit [0-9a-f]+\)$')
PLACEHOLDER = re.compile(
    r'^(wip|fix(es|ed)?|update[sd]?|changes?|misc|stuff|temp|tmp|test(ing)?|'
    r'cleanup|tweaks?|minor|edits?|commit|save|\.+|-+)$', re.IGNORECASE)
TEMPLATE = """\
Expected format:

  <Imperative subject, 72 characters or fewer>

  What: the behaviour or files this changes, in plain words.
  Why: the problem it fixes or the reason it is needed.
  Verification: the checks you ran, or why none apply.

  Milestone: M2   (the milestone in project/milestones this advances, or "none")
"""


def clean(message):
    """Drop git comments, the verbose-diff section and trailing whitespace."""
    message = message.split(SCISSORS, 1)[0]
    lines = [line.rstrip() for line in message.splitlines() if not line.startswith('#')]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return lines


def named_milestones(message):
    """Milestone IDs (upper case) and "none" from the message's Milestone trailers."""
    found = []
    for line in clean(message):
        trailer = MILESTONE_TRAILER.match(line.strip())
        if trailer:
            found += [t.upper() if t.lower() != 'none' else 'none'
                      for t in MILESTONE_TOKEN.findall(trailer.group(1))]
    return found


def milestone_problems(message, known):
    """Reasons the Milestone trailer is missing or wrong; known is the set of valid IDs."""
    named = named_milestones(message)
    if not named:
        return ['Add a "Milestone: M<n>" trailer naming the milestone this change advances '
                '(python tools/project_milestones.py list), or "Milestone: none" when it is '
                'outside every milestone.']
    unknown = sorted({n for n in named if n != 'none' and n not in known})
    if unknown:
        return [f'Unknown milestone {", ".join(unknown)}; valid IDs are '
                f'{", ".join(sorted(known, key=lambda i: int(i[1:]))) or "(none defined)"}.']
    return []


def working_tree_milestones():
    """Milestone IDs defined in this checkout, or None when there is no tracker."""
    folder = ROOT / TRACKER
    if not folder.is_dir():
        return None
    return {m.group(1) for p in folder.iterdir() if (m := MILESTONE_FILE.match(p.name))}


def problems(message, milestones=None):
    """Return a list of reasons the message is not acceptable (empty when fine).

    milestones is the set of valid milestone IDs; None skips the milestone rule.
    """
    lines = clean(message)
    if not lines:
        return ['The commit message is empty.']
    subject = lines[0].strip()
    if subject.startswith('Merge '):
        return []  # Git-generated merge messages; the merged commits are checked themselves.
    found = []
    if len(subject) > MAX_SUBJECT:
        found.append(f'The subject line is {len(subject)} characters; keep it to {MAX_SUBJECT}.')
    if PLACEHOLDER.match(subject.rstrip('.!')):
        found.append(f'The subject "{subject}" does not describe the change.')
    if len(lines) > 1 and lines[1].strip():
        found.append('Leave a blank line between the subject and the explanation.')
    body = [line for line in lines[1:]
            if not TRAILER.match(line.strip()) and not CHERRY_PICK.match(line.strip())]
    words = len(' '.join(body).split())
    if words < MIN_BODY_WORDS:
        found.append(
            f'The explanation has {words} words; describe what changed and why in at least '
            f'{MIN_BODY_WORDS} words below the subject line.')
    if milestones is not None:
        found += milestone_problems(message, milestones)
    return found


def report(label, found):
    print(f'{label}:', file=sys.stderr)
    for item in found:
        print(f'  - {item}', file=sys.stderr)


def other_remote_branches(branch, remote='origin'):
    """Remote-tracking refs except the pushed branch itself (and the remote HEAD alias)."""
    out = subprocess.run(['git', 'for-each-ref', '--format=%(refname)', f'refs/remotes/{remote}'],
                         check=True, capture_output=True, text=True, encoding='utf-8').stdout
    skip = {f'refs/remotes/{remote}/{branch}', f'refs/remotes/{remote}/HEAD'}
    return [ref for ref in out.split() if ref not in skip]


def new_branch_revisions(sha, branch, remote='origin'):
    """git log arguments for the commits a newly pushed branch adds.

    Commits that are already on another branch of the remote were checked (or
    predate this rule) when they arrived there, so only the rest are checked.
    """
    others = other_remote_branches(branch, remote)
    return [sha, '--not', *others] if others else [sha]


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True,
                          encoding='utf-8').stdout


def commits(revisions):
    """(sha, message) for each non-merge commit in the revisions."""
    out = git('log', '--no-merges', '--format=%H%x00%B%x01', *revisions)
    for record in out.split('\x01'):
        record = record.strip('\n')
        if record:
            yield tuple(record.split('\x00', 1))


def commit_milestones(sha):
    """Milestone IDs defined in a commit's own tree, or None if it predates the tracker."""
    names = git('ls-tree', '--name-only', sha, TRACKER + '/').split()
    if not names:
        return None
    return {m.group(1) for n in names if (m := MILESTONE_FILE.match(n.rsplit('/', 1)[-1]))}


def check_range(spec):
    revisions = spec if isinstance(spec, list) else [spec]
    failed = 0
    checked = 0
    for sha, message in commits(revisions):
        checked += 1
        found = problems(message, commit_milestones(sha))
        if found:
            failed += 1
            subject = (clean(message) or [''])[0]
            report(f'{sha[:12]} {subject}', found)
    if failed:
        print(f'\n{failed} of {checked} commit(s) do not explain their change.\n', file=sys.stderr)
        print(TEMPLATE, file=sys.stderr)
        return 1
    print(f'{checked} commit message(s) explain their change.')
    return 0


def tracker_problems(base, head):
    """Milestones named by commits in base..head whose file the branch never changed."""
    named = set()
    for sha, message in commits([f'{base}..{head}']):
        if commit_milestones(sha) is not None:
            named |= {n for n in named_milestones(message) if n != 'none'}
    if not named:
        return []
    changed = git('diff', '--name-only', f'{base}...{head}', '--', TRACKER).split()
    touched = {m.group(1) for path in changed
               if (m := MILESTONE_FILE.match(path.rsplit('/', 1)[-1]))}
    return [f'Commits name {m} but {TRACKER}/{m}-*.md was not updated on this branch; add a '
            f'progress-log line (python tools/project_milestones.py log {m} "...") and update '
            'its issues and status.' for m in sorted(named - touched, key=lambda i: int(i[1:]))]


def check_tracker(base, head):
    found = tracker_problems(base, head)
    if found:
        report('The project milestones were not kept current', found)
        return 1
    print('Every milestone named by these commits was updated on the branch.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('message_file', nargs='?', type=Path)
    group.add_argument('--range', dest='range_spec')
    group.add_argument('--new-branch', nargs=2, metavar=('SHA', 'BRANCH'),
                       help='check commits of a newly pushed branch that no other remote branch has')
    group.add_argument('--tracker', nargs=2, metavar=('BASE', 'HEAD'),
                       help='require the milestone files named in BASE..HEAD to be updated')
    args = parser.parse_args(argv)
    if args.tracker:
        return check_tracker(*args.tracker)
    if args.new_branch:
        return check_range(new_branch_revisions(*args.new_branch))
    if args.range_spec:
        return check_range(args.range_spec)
    found = problems(args.message_file.read_text(encoding='utf-8', errors='replace'),
                     working_tree_milestones())
    if found:
        report('Commit rejected: the message must explain the change', found)
        print('\n' + TEMPLATE, file=sys.stderr)
        print('Your message was kept in .git/COMMIT_EDITMSG; reuse it with '
              '"git commit -e -F .git/COMMIT_EDITMSG".', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
