"""Read, check and update the project milestones in project/milestones/.

Every coding tool and person keeps these files current (see "Keep the project and
milestones current" in AGENTS.md). Each milestone is one Markdown file named
M<n>-short-name.md with this shape:

  # M2: Title
  - Status: planned | in progress | blocked | done
  - Updated: YYYY-MM-DD
  ...
  ## Issues
  - [ ] #52 Title - note
  - [x] #36 Title - note
  ...
  ## Progress log
  - YYYY-MM-DD: what happened

Usage:
  python tools/project_milestones.py list
  python tools/project_milestones.py check
  python tools/project_milestones.py find N            milestone that lists issue N
  python tools/project_milestones.py log M2 "text"     append a dated progress line
  python tools/project_milestones.py issue N --done    tick (or --open to untick) issue N
  python tools/project_milestones.py status M2 blocked
  python tools/project_milestones.py audit [--repo OWNER/NAME]
      compare with GitHub issues (needs gh): open issues in no milestone, ticked issues
      still open, unticked issues already closed.
"""
import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MILESTONES = ROOT / 'project' / 'milestones'
STATUSES = ('planned', 'in progress', 'blocked', 'done')
FILE_NAME = re.compile(r'^(M\d+)-[a-z0-9-]+\.md$')
HEADING = re.compile(r'^# (M\d+): (.+)$')
FIELD = re.compile(r'^- (Status|Updated|Target|Repos): (.*)$')
ISSUE = re.compile(r'^- \[( |x)\] #(\d+)\b(.*)$')
LOG_SECTION = '## Progress log'


@dataclass
class Milestone:
    path: Path
    id: str = ''
    title: str = ''
    fields: dict = field(default_factory=dict)
    issues: dict = field(default_factory=dict)  # number -> done

    @property
    def status(self):
        return self.fields.get('Status', '')


def parse(path):
    milestone = Milestone(path)
    section = ''
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            section = line[3:].strip().lower()
            continue
        heading = HEADING.match(line)
        if heading and not milestone.id:
            milestone.id, milestone.title = heading.group(1), heading.group(2).strip()
            continue
        found = FIELD.match(line)
        if found and not section:
            milestone.fields[found.group(1)] = found.group(2).strip()
            continue
        issue = ISSUE.match(line)
        if issue and section == 'issues':
            milestone.issues[int(issue.group(2))] = issue.group(1) == 'x'
    return milestone


def load(root=None):
    folder = (Path(root) / 'project' / 'milestones') if root else MILESTONES
    if not folder.is_dir():
        return []
    return sorted((parse(p) for p in folder.glob('*.md')), key=lambda m: int(m.id[1:] or 0))


def ids(root=None):
    return {m.id for m in load(root)}


def problems(milestones):
    found = []
    owners = {}
    seen = {}
    for m in milestones:
        name = m.path.name
        match = FILE_NAME.match(name)
        if not match:
            found.append(f'{name}: name it M<n>-short-name.md (lower case, hyphens).')
        if not m.id:
            found.append(f'{name}: first heading must be "# M<n>: Title".')
            continue
        if match and match.group(1) != m.id:
            found.append(f'{name}: file name says {match.group(1)} but the heading says {m.id}.')
        if m.id in seen:
            found.append(f'{name}: {m.id} is also used by {seen[m.id]}.')
        seen[m.id] = name
        if m.status not in STATUSES:
            found.append(f'{name}: Status must be one of {", ".join(STATUSES)} '
                         f'(found "{m.status}").')
        try:
            date.fromisoformat(m.fields.get('Updated', ''))
        except ValueError:
            found.append(f'{name}: Updated must be a YYYY-MM-DD date.')
        text = m.path.read_text(encoding='utf-8')
        for section in ('## Goal', '## Done when', '## Issues', LOG_SECTION):
            if section not in text.splitlines():
                found.append(f'{name}: missing the "{section}" section.')
        # A bad merge can leave two header fields or the same issue twice; the parser would
        # silently keep only the last one.
        header = text.split('\n## ', 1)[0].splitlines()
        for key in ('Status', 'Updated', 'Target', 'Repos'):
            if sum(1 for line in header if line.startswith(f'- {key}: ')) > 1:
                found.append(f'{name}: "- {key}:" appears more than once.')
        numbers = [ISSUE.match(line).group(2) for line in text.splitlines() if ISSUE.match(line)]
        for number in sorted(set(n for n in numbers if numbers.count(n) > 1), key=int):
            found.append(f'{name}: #{number} is listed more than once.')
        if any(line.startswith(('<<<<<<< ', '>>>>>>> ')) for line in text.splitlines()):
            found.append(f'{name}: contains unresolved merge conflict markers.')
        for number in m.issues:
            if number in owners:
                found.append(f'#{number} is listed in both {owners[number]} and {m.id}; '
                             'keep each issue in one milestone.')
            owners[number] = m.id
        if m.status == 'done' and not all(m.issues.values()):
            open_ = ', '.join(f'#{n}' for n, done in m.issues.items() if not done)
            found.append(f'{name}: marked done but {open_} not ticked.')
    return found


def find(number, milestones=None):
    for m in milestones if milestones is not None else load():
        if number in m.issues:
            return m
    return None


def by_id(milestone_id):
    for m in load():
        if m.id == milestone_id.upper():
            return m
    raise SystemExit(f'No milestone {milestone_id}; see python tools/project_milestones.py list')


def touch(text, today=None):
    """Set the Updated field to today."""
    stamp = (today or date.today()).isoformat()
    return re.sub(r'^- Updated: .*$', f'- Updated: {stamp}', text, count=1, flags=re.M)


def append_log(text, entry, today=None):
    stamp = (today or date.today()).isoformat()
    line = f'- {stamp}: {entry.strip()}'
    if LOG_SECTION not in text:
        text = text.rstrip('\n') + f'\n\n{LOG_SECTION}\n'
    return touch(text.rstrip('\n') + '\n' + line + '\n', today)


def set_issue(text, number, done, today=None):
    pattern = re.compile(rf'^- \[[ x]\] #{number}\b', re.M)
    if not pattern.search(text):
        raise SystemExit(f'#{number} is not listed in this milestone.')
    return touch(pattern.sub(f'- [{"x" if done else " "}] #{number}', text, count=1), today)


def set_status(text, status, today=None):
    if status not in STATUSES:
        raise SystemExit(f'Status must be one of: {", ".join(STATUSES)}')
    return touch(re.sub(r'^- Status: .*$', f'- Status: {status}', text, count=1, flags=re.M),
                 today)


def rewrite(m, change):
    m.path.write_text(change(m.path.read_text(encoding='utf-8')), encoding='utf-8')
    print(f'Updated {m.path.relative_to(ROOT)}')


def cmd_list(_args):
    milestones = load()
    print(f'{"ID":<4} {"Status":<12} {"Issues":<7} {"Updated":<11} Title')
    for m in milestones:
        done = sum(m.issues.values())
        print(f'{m.id:<4} {m.status:<12} {f"{done}/{len(m.issues)}":<7} '
              f'{m.fields.get("Updated", ""):<11} {m.title}')


def cmd_check(_args):
    found = problems(load())
    for item in found:
        print(f'  - {item}', file=sys.stderr)
    if found:
        print(f'{len(found)} problem(s) in project/milestones.', file=sys.stderr)
        return 1
    print(f'{len(load())} milestone(s) checked.')
    return 0


def cmd_find(args):
    m = find(args.number)
    if not m:
        print(f'#{args.number} is not in any milestone.')
        return 1
    print(m.id)
    return 0


def cmd_log(args):
    rewrite(by_id(args.milestone), lambda text: append_log(text, args.text))


def cmd_issue(args):
    m = find(args.number)
    if not m:
        raise SystemExit(f'#{args.number} is not in any milestone; add it to the right file first.')
    rewrite(m, lambda text: set_issue(text, args.number, not args.open))


def cmd_status(args):
    rewrite(by_id(args.milestone), lambda text: set_status(text, args.status))


def audit(milestones, open_issues, closed_numbers):
    """Return lines describing where the milestones and GitHub disagree."""
    listed = {n: m.id for m in milestones for n in m.issues}
    ticked = {n for m in milestones for n, done in m.issues.items() if done}
    lines = []
    for issue in sorted(open_issues, key=lambda i: i['number']):
        n = issue['number']
        if n not in listed:
            lines.append(f'#{n} is open but in no milestone: {issue["title"]}')
        elif n in ticked:
            lines.append(f'#{n} is ticked in {listed[n]} but still open on GitHub.')
    for n in sorted(closed_numbers & set(listed) - ticked):
        lines.append(f'#{n} is closed on GitHub but not ticked in {listed[n]}.')
    return lines


def cmd_audit(args):
    def gh_issues(state):
        repo = ['--repo', args.repo] if args.repo else []
        out = subprocess.run(['gh', 'issue', 'list', '--state', state, '--limit', '500',
                              '--json', 'number,title', *repo], cwd=ROOT, capture_output=True,
                             text=True, encoding='utf-8')
        if out.returncode:
            raise SystemExit(out.stderr.strip() or 'gh issue list failed')
        return json.loads(out.stdout)
    lines = audit(load(), gh_issues('open'), {i['number'] for i in gh_issues('closed')})
    for line in lines:
        print(f'- {line}')
    print('Milestones and GitHub issues agree.' if not lines else
          f'{len(lines)} difference(s); update the milestone files or the issues.')
    return 1 if lines else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list').set_defaults(func=cmd_list)
    sub.add_parser('check').set_defaults(func=cmd_check)
    p = sub.add_parser('find')
    p.add_argument('number', type=int)
    p.set_defaults(func=cmd_find)
    p = sub.add_parser('log')
    p.add_argument('milestone')
    p.add_argument('text')
    p.set_defaults(func=cmd_log)
    p = sub.add_parser('issue')
    p.add_argument('number', type=int)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--done', action='store_true')
    group.add_argument('--open', action='store_true')
    p.set_defaults(func=cmd_issue)
    p = sub.add_parser('status')
    p.add_argument('milestone')
    p.add_argument('status', choices=STATUSES)
    p.set_defaults(func=cmd_status)
    p = sub.add_parser('audit')
    p.add_argument('--repo')
    p.set_defaults(func=cmd_audit)
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == '__main__':
    sys.exit(main())
