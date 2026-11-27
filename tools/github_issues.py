"""Review open GitHub issues and keep the issue being worked on up to date.

Works from any coding tool or a terminal; needs the GitHub CLI (`gh`) logged in.

  python tools/github_issues.py review [--repo OWNER/NAME] [--stale-days 14]
      Open issues grouped by kind (urgent/security, bugs, features, other), with
      age, last update, comments, assignees and an "in progress" marker.
  python tools/github_issues.py current
      The issue number the current branch is for (issue-49-..., fix/49-..., gh-49).
  python tools/github_issues.py start N
      Assign yourself, add the "in progress" label and comment with the branch.
  python tools/github_issues.py update N --body "..."   (or --body-file FILE)
      Post a progress comment.
  python tools/github_issues.py pause N [--body "..."]
      Remove the "in progress" label (and optionally say why).
  python tools/github_issues.py link-commit MESSAGE_FILE
      Used by .githooks/prepare-commit-msg: adds a "Refs: #N" trailer for the
      branch's issue so pushed commits appear on that issue automatically.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_PROGRESS = 'in progress'
FIELDS = 'number,title,labels,assignees,createdAt,updatedAt,comments,url'
BRANCH_ISSUE = re.compile(r'(?:^|/)(?:issue-?|gh-?)?(\d+)(?=-|_|$)', re.IGNORECASE)
GROUPS = (
    ('Urgent and security', re.compile(r'\burgent\b|\bsecurity\b|\bleak', re.I), {'security'}),
    ('Bugs', re.compile(r'\bbug\b|not (?:triggering|registering|working)|doesn.t|don.t seem|'
                        r'wrong|missing|too late|rubber-?band|backwards|under ?ground|keeps', re.I),
     {'bug'}),
    ('Features and proposals', re.compile(r'feature request|\bproposal\b|\bpull\b|module|'
                                          r'self-hosted|\bmap update\b', re.I),
     {'enhancement'}),
)


def run(*args, capture=True):
    result = subprocess.run(args, cwd=ROOT, capture_output=capture, text=True, encoding='utf-8')
    if result.returncode:
        raise SystemExit((result.stderr or '').strip() or f'{args[0]} failed')
    return result.stdout if capture else ''


def gh(*args):
    return run('gh', *args)


def current_branch():
    return run('git', 'rev-parse', '--abbrev-ref', 'HEAD').strip()


def issue_from_branch(branch):
    """Return the issue number a branch name refers to, or None."""
    match = BRANCH_ISSUE.search(branch or '')
    return int(match.group(1)) if match else None


def classify(issue):
    labels = {label['name'].lower() for label in issue.get('labels', [])}
    # Features are matched before bugs so "Map update: ... doesn't ..." stays a feature.
    for name, pattern, label_names in (GROUPS[0], GROUPS[2], GROUPS[1]):
        if labels & label_names or pattern.search(issue['title']):
            return name
    return 'Other'


def days_since(stamp, now):
    return (now - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).days


def render_review(issues, now=None, stale_days=14, repo=''):
    """Markdown summary of open issues, grouped by kind."""
    now = now or datetime.now(timezone.utc)
    if not issues:
        return f'No open issues{" in " + repo if repo else ""}.'
    groups = {}
    for issue in sorted(issues, key=lambda i: i['updatedAt'], reverse=True):
        groups.setdefault(classify(issue), []).append(issue)
    in_progress = [i for i in issues
                   if IN_PROGRESS in {label['name'].lower() for label in i.get('labels', [])}]
    unassigned = sum(1 for i in issues if not i.get('assignees'))
    stale = [i for i in issues if days_since(i['updatedAt'], now) >= stale_days]
    lines = [f'# Open issues{" - " + repo if repo else ""}', '',
             f'{len(issues)} open | {len(in_progress)} in progress | {unassigned} unassigned | '
             f'{len(stale)} without updates for {stale_days}+ days', '']
    for name in [g[0] for g in GROUPS] + ['Other']:
        if name not in groups:
            continue
        lines += [f'## {name} ({len(groups[name])})', '']
        for issue in groups[name]:
            labels = {label['name'].lower() for label in issue.get('labels', [])}
            marks = []
            if IN_PROGRESS in labels:
                marks.append('IN PROGRESS')
            if 'host + client' in issue['title'].lower():
                marks.append('needs both repos')
            who = ', '.join('@' + a['login'] for a in issue.get('assignees', [])) or 'unassigned'
            comments = issue.get('comments') or []
            count = len(comments) if isinstance(comments, list) else int(comments)
            lines.append(
                f'- #{issue["number"]} {issue["title"]}'
                + (f' [{"; ".join(marks)}]' if marks else '')
                + f' - opened {days_since(issue["createdAt"], now)}d ago, updated '
                f'{days_since(issue["updatedAt"], now)}d ago, {count} comment(s), {who}')
        lines.append('')
    return '\n'.join(lines).rstrip()


def repo_args(repo):
    return ['--repo', repo] if repo else []


def cmd_review(args):
    issues = json.loads(gh('issue', 'list', '--state', 'open', '--limit', '200',
                           '--json', FIELDS, *repo_args(args.repo)))
    print(render_review(issues, stale_days=args.stale_days, repo=args.repo or ''))


def cmd_current(_args):
    branch = current_branch()
    number = issue_from_branch(branch)
    if number is None:
        print(f'Branch "{branch}" does not name an issue (use e.g. issue-49-short-name).')
        return 1
    print(number)
    return 0


def ensure_label():
    gh('label', 'create', IN_PROGRESS, '--color', 'fbca04', '--force',
       '--description', 'Someone is actively working on this')


def cmd_start(args):
    ensure_label()
    gh('issue', 'edit', str(args.number), '--add-assignee', '@me', '--add-label', IN_PROGRESS)
    branch = current_branch()
    body = f'Work started on branch `{branch}`.'
    if issue_from_branch(branch) != args.number:
        body += (f' (This branch name does not include #{args.number}; commits only link here '
                 'automatically from a branch such as `issue-%d-short-name`.)' % args.number)
    if args.body:
        body += '\n\n' + args.body
    gh('issue', 'comment', str(args.number), '--body', body)
    print(f'#{args.number}: assigned, labelled "{IN_PROGRESS}", start comment posted.')


def read_body(args):
    if getattr(args, 'body_file', None):
        return Path(args.body_file).read_text(encoding='utf-8')
    return args.body or ''


def cmd_update(args):
    body = read_body(args).strip()
    if not body:
        raise SystemExit('Nothing to post: give --body or --body-file.')
    gh('issue', 'comment', str(args.number), '--body', body)
    print(f'#{args.number}: progress comment posted.')


def cmd_pause(args):
    gh('issue', 'edit', str(args.number), '--remove-label', IN_PROGRESS)
    if args.body:
        gh('issue', 'comment', str(args.number), '--body', args.body)
    print(f'#{args.number}: "{IN_PROGRESS}" label removed.')


def add_issue_trailer(message, number):
    """Return the message with a Refs trailer for the issue, unless it already mentions it."""
    if re.search(rf'#{number}\b', message):
        return message
    return subprocess.run(['git', 'interpret-trailers', '--trailer', f'Refs: #{number}'],
                          input=message, capture_output=True, text=True, encoding='utf-8',
                          cwd=ROOT, check=True).stdout


def add_milestone_trailer(message, number, find=None):
    """Add "Milestone: Mn" for the milestone that lists the issue, unless one is present."""
    if re.search(r'^milestones?\s*:', message, re.IGNORECASE | re.MULTILINE):
        return message
    try:
        if find is None:
            import project_milestones
            find = project_milestones.find
        milestone = find(number)
    except Exception:  # a malformed milestone file must never block a commit here
        return message
    if milestone is None:
        return message
    return subprocess.run(['git', 'interpret-trailers', '--trailer', f'Milestone: {milestone.id}'],
                          input=message, capture_output=True, text=True, encoding='utf-8',
                          cwd=ROOT, check=True).stdout


def cmd_link_commit(args):
    if args.source in ('merge', 'squash'):
        return 0
    try:
        number = issue_from_branch(current_branch())
    except SystemExit:
        return 0  # e.g. the first commit of a repository; never block a commit here
    if number is None:
        return 0
    path = Path(args.message_file)
    message = path.read_text(encoding='utf-8')
    updated = add_milestone_trailer(add_issue_trailer(message, number), number)
    if updated != message:
        path.write_text(updated, encoding='utf-8')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('review')
    p.add_argument('--repo')
    p.add_argument('--stale-days', type=int, default=14)
    p.set_defaults(func=cmd_review)
    sub.add_parser('current').set_defaults(func=cmd_current)
    p = sub.add_parser('start')
    p.add_argument('number', type=int)
    p.add_argument('--body')
    p.set_defaults(func=cmd_start)
    p = sub.add_parser('update')
    p.add_argument('number', type=int)
    group = p.add_mutually_exclusive_group()
    group.add_argument('--body')
    group.add_argument('--body-file')
    p.set_defaults(func=cmd_update)
    p = sub.add_parser('pause')
    p.add_argument('number', type=int)
    p.add_argument('--body')
    p.set_defaults(func=cmd_pause)
    p = sub.add_parser('link-commit')
    p.add_argument('message_file')
    p.add_argument('source', nargs='?', default='')
    p.add_argument('sha', nargs='?', default='')
    p.set_defaults(func=cmd_link_commit)
    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == '__main__':
    sys.exit(main())
