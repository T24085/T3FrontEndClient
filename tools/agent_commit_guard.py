"""Coding-agent shell hook: keep agents from committing without an explanation.

Blocks a shell command that runs `git commit` when it would skip the commit-msg
hook (--no-verify, -n, or a core.hooksPath override) or when this checkout has
not installed the versioned hooks yet. The commit-msg hook itself then rejects
messages that do not explain the change (tools/check_commit_message.py).

One script serves every agent tool that supports shell hooks:

* Claude Code (.claude/settings.json, PreToolUse): reads {"tool_input": {"command": ...}};
  blocks with exit code 2 and a reason on stderr.
* Cursor (.cursor/hooks.json, beforeShellExecution) with --format cursor: reads
  {"command": ...}; always answers with JSON {"permission": "allow" | "deny", ...}
  and also exits 2 when denying.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT_COMMIT = re.compile(r'\bgit\b[^;&|\n]*?\bcommit\b[^;&|\n]*')
NO_VERIFY = re.compile(r'--no-verify\b|(?:^|\s)-[a-zA-Z]*n[a-zA-Z]*(?=\s|$)')
HOOKS_OVERRIDE = re.compile(r'core\.hooksPath\s*=', re.IGNORECASE)
BYPASS = ('Commits in this repository must pass the commit-msg hook. Do not use --no-verify, '
          '-n or a core.hooksPath override; write a message that explains what changed and '
          'why (see "Explain every change before it commits" in AGENTS.md).')
NOT_INSTALLED = ('The commit-explanation hook is not installed in this checkout. Run '
                 '"python tools/install_git_hooks.py" first, then commit with a message that '
                 'explains what changed and why (see AGENTS.md).')


def hooks_installed():
    configured = subprocess.run(['git', '-C', str(ROOT), 'config', '--get', 'core.hooksPath'],
                                capture_output=True, text=True).stdout.strip()
    return configured == '.githooks'


def reason_to_block(command, installed=hooks_installed):
    """Return why the command must not run, or None when it may."""
    commits = GIT_COMMIT.findall(command or '')
    if not commits:
        return None
    for segment in commits:
        # Ignore flag-like text inside the quoted message itself.
        flags = re.sub(r'"[^"]*"|\'[^\']*\'', '', segment)
        if NO_VERIFY.search(flags) or HOOKS_OVERRIDE.search(flags):
            return BYPASS
    if not installed():
        return NOT_INSTALLED
    return None


def command_from(payload, fmt):
    if not isinstance(payload, dict):
        return ''
    if fmt == 'cursor':
        return payload.get('command') or ''
    return (payload.get('tool_input') or {}).get('command') or ''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--format', choices=('claude', 'cursor'), default='claude')
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    reason = reason_to_block(command_from(payload, args.format))
    if args.format == 'cursor':
        answer = {'permission': 'allow'}
        if reason:
            answer = {'permission': 'deny', 'user_message': reason, 'agent_message': reason}
        print(json.dumps(answer))
    elif reason:
        print(reason, file=sys.stderr)
    return 2 if reason else 0


if __name__ == '__main__':
    sys.exit(main())
