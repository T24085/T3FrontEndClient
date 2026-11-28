"""Git merge driver for project/milestones/*.md.

Registered by tools/install_git_hooks.py and selected by .gitattributes. Git runs it as
``merge_milestone_file.py %O %A %B``: the common ancestor, our version (the result is written
here) and theirs.

Milestone files change in predictable ways, so most conflicts have one right answer:
- progress-log lines ("- YYYY-MM-DD: ...") from both sides are all kept, ordered by date;
- "- Updated:" keeps the later date;
- issue lines ("- [ ] #N ...") from both sides are kept, one line per issue (ours wins);
- any other line both sides kept, such as the same note wrapped differently, is kept once.
Anything else, such as two different "- Status:" values, stays a normal conflict for a person to
decide, and the driver exits 1 so Git reports it.
"""
import re
import subprocess
import sys
from pathlib import Path

HUNK = re.compile(r'<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n', re.S)
LOG = re.compile(r'- (\d{4}-\d{2}-\d{2}): ')
UPDATED = re.compile(r'- Updated: (\d{4}-\d{2}-\d{2})\n')
ISSUE = re.compile(r'- \[[ x]\] #(\d+)\b')
FIELD = re.compile(r'- (Status|Target|Repos): ')


def entries(text):
    """Split a hunk side into entries: a "- " line plus its indented continuation lines."""
    out = []
    for line in text.splitlines(True):
        if out and not line.startswith('- ') and line.startswith('  '):
            out[-1] += line
        else:
            out.append(line)
    return out


def normal(entry):
    return re.sub(r'\s+', ' ', entry.strip().lstrip('-').strip())


def resolve(ours, theirs):
    """Return the merged text for one conflict, or None when a person has to decide."""
    a, b = entries(ours), entries(theirs)
    every = [e for e in a + b if e.strip()]
    if every and all(UPDATED.fullmatch(e) for e in every):
        return max(every, key=lambda e: UPDATED.fullmatch(e).group(1))
    if any(FIELD.match(e) for e in every):
        return None
    merged, seen_text, seen_issue = [], set(), set()
    for e in a + b:
        if not e.strip():
            if merged and merged[-1].strip():
                merged.append(e)
            continue
        issue = ISSUE.match(e)
        if issue:
            if issue.group(1) in seen_issue:
                continue
            seen_issue.add(issue.group(1))
        elif normal(e) in seen_text:
            continue
        seen_text.add(normal(e))
        merged.append(e)
    while merged and not merged[-1].strip():
        merged.pop()
    logs = [e for e in merged if LOG.match(e)]
    if logs and len(logs) == len([e for e in merged if e.strip()]):
        merged = sorted(logs, key=lambda e: LOG.match(e).group(1))
    return ''.join(merged)


def merge_text(text):
    """Resolve every conflict in ``text``; return the new text and whether any remain."""
    unresolved = False

    def pick(match):
        nonlocal unresolved
        result = resolve(match.group(1), match.group(2))
        if result is None:
            unresolved = True
            return match.group(0)
        return result

    return HUNK.sub(pick, text), unresolved


def main(base, ours, theirs):
    merged = subprocess.run(['git', 'merge-file', '-p', '-L', 'ours', '-L', 'base', '-L', 'theirs',
                             ours, base, theirs], capture_output=True)
    if merged.returncode < 0:
        return 2
    text, unresolved = merge_text(merged.stdout.decode('utf-8'))
    Path(ours).write_bytes(text.encode('utf-8'))
    return 1 if unresolved else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:4]))
