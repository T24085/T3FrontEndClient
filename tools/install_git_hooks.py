"""Point this checkout at the versioned hooks in .githooks and the commit template.

Run once per clone: python tools/install_git_hooks.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    subprocess.run(['git', '-C', str(ROOT), *args], check=True)


def main():
    git('config', 'core.hooksPath', '.githooks')
    git('config', 'commit.template', '.gitmessage')
    for hook in (ROOT / '.githooks').iterdir():
        hook.chmod(hook.stat().st_mode | 0o111)
    # .gitattributes sends project/milestones/*.md through this driver (merge=milestones).
    git('config', 'merge.milestones.name', 'Milestone files: keep both progress logs and issue lists')
    # A branch from before the driver existed lacks the script, so fall back to Git's normal
    # three-way merge (ordinary conflict markers) when it is missing.
    git('config', 'merge.milestones.driver',
        'if [ -f tools/merge_milestone_file.py ]; then '
        f'"{Path(sys.executable).as_posix()}" tools/merge_milestone_file.py %O %A %B; '
        'else git merge-file -L ours -L base -L theirs %A %O %B; fi')
    print('Git hooks installed: commits must explain what changed and why, and commits on an '
          'issue branch (issue-49-...) are linked to that issue. Milestone files now merge '
          'their progress logs and issue lists automatically.')


if __name__ == '__main__':
    main()
