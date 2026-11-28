# Engineering workflow

This is the working source repository for the TRIBES 3 frontend client. The paired repository is https://github.com/T24085/T3BackEndServer.

Edit this checkout for new work. Legacy research directories and installed packages are reference/deployment inputs, not the development source. Use feature branches for fixes. Preserve source provenance and native process/Job ownership.

## Main is protected

Nobody commits or pushes directly to `main`: not agents, not people, not org owners. This applies to every harness (Claude Code, Gemini CLI, Cursor, Codex, Copilot and others).

1. Commit on the working branch and push that branch. Contributors with Read access (`T3-Mod-Devs`) push to their fork.
2. Open a pull request into `main`. A member of the `T3-Mod-Admins` team other than the author must approve it, and a `T3-Mod-Admins` member merges it. Nobody approves or merges their own pull request.
3. Never push to `main`, never commit while `main` is checked out, and never write to `main` through the GitHub API or web editor.

GitHub enforces this with the "Protect main" ruleset (pull request with code-owner approval from `T3-Mod-Admins`, no force-push or deletion, no bypass) and `.github/CODEOWNERS`.

## PR branch lifecycle

Use the [deploy-game-server skill](.claude/skills/deploy-game-server/SKILL.md) when taking a change through PR review or preparing and verifying a production game server release.

- Keep 5–10 remote branches per repository as a working target, including the default branch. Before creating an issue, bug-fix, feature or maintenance branch, check open PRs and reuse an appropriate branch. Above 10, review the backlog for branches ready to retire and record why active branches still need to exist.
- Keep one reusable developer branch named `dev/<github-login>` for each contributor with canonical write access. Use the lowercase GitHub login. Start from current `main` and open an independently reviewed PR to `main`. Contributors with read access use the same naming in their own forks.
- Keep issue branches for tracked fixes, concurrent changes, and PR stacks. A developer branch can carry one review scope at a time. Before reusing it, verify the previous work reached `main` and fast-forward or merge current `main` into it. Keep developer branches out of merged-topic cleanup.
- Apply temporary branch deletion to issue, feature, and maintenance topics. When its PR merges, verify that GitHub removed the head branch. If the branch remains, check the latest remote tip, confirm its work reached the intended target and check for open PRs using it as a head or base. Remove the remote branch once those checks pass. A matching merged PR head plus its integration commit in the target also verifies a squash merge.
- Keep branches with unmerged work, dependent PRs, or an ongoing release or maintenance purpose. For stacked PRs, retarget the dependents before deleting their previous base and verify the full stack reaches the intended target. Preserve local worktrees and local changes. For fork branches, the contributor handles deletion if you lack access.
- Agents track branch cleanup on the linked issue or PR. Record open PR links, branch dependencies and blockers at handoff. After a merge, record whether the branch was deleted or why it is retained, then recheck retained branches when their blockers clear. Branch cleanup and issue closure each follow their own completion checks.

## Harness parity

Every agent rule, skill, subagent or hook must work in every harness this project uses: Claude Code, Gemini CLI, Cursor, Codex, GitHub Copilot, and any harness added later. Nothing is Claude-only, Cursor-only or Gemini-only.

1. **Rules live in `AGENTS.md`.** Write a new rule here, not in a harness file. `CLAUDE.md` and `GEMINI.md` only import this file, `.github/copilot-instructions.md` points to it, and Codex and Cursor read it directly.
2. **Skills and subagents ship for every harness in the same change.** The full steps live in one plain Markdown file (`.claude/skills/<name>/SKILL.md`, or `.claude/agents/<name>.md`) that any tool can read. The same change adds `.cursor/rules/<name>.mdc` pointing at it and lists it under "Skills" in `GEMINI.md`. If the steps need a command, put it in a script under `tools/` so every harness runs the same code.
3. **Hooks ship for every harness that supports them.** Put the logic in one script under `tools/`, then wire it into `.claude/settings.json`, `.cursor/hooks.json` and `.gemini/settings.json` in the same change. For harnesses without hooks (Codex, Copilot), state the rule in this file so they follow it by instruction.
4. **Say when a harness can't do it.** If a harness cannot support something, say so in the change and in this file, with what that harness does instead.

The T3BackEndServer repository holds the reference setup (shared skills, the agent commit guard and `test_harness_parity.py`).

## GitHub coordination

- Before editing, check [active work in this repo](https://github.com/T24085/T3FrontEndClient/issues?q=is%3Aissue+is%3Aopen+label%3A%22in+progress%22) and the [paired repo](https://github.com/T24085/T3BackEndServer/issues?q=is%3Aissue+is%3Aopen+label%3A%22in+progress%22). Reuse the relevant issue or open one if needed. Coordinate overlapping work on the issue before editing the same area.
- Claim the issue with the `in progress` label. Post the owner or agent identifier, scope, branch, and start date and time in Central Time. Link the paired issue for work that spans both repos.
- Update the issue when the scope or status changes, when blocked, and at handoff. Include the branch, commit or PR, verification results, and what is still pending. Remove `in progress` when active work stops. Match the visibility of the repo when sharing details, and keep credentials out of issues.
- When a tested fix is in a PR, apply `fix ready` and post a plain-language status such as **Fix ready, pending server deployment**. Link the PR, name the target server or client update feed, and state what passed and which symptoms still need verification.
- For issues that require rollout, keep the issue open through release. Update it when the fix ships, record the deployed revision and live verification result, and close it once the reported symptoms are resolved. If rollout or verification is blocked, record the blocker and next action on the issue.

Verify pull request checks in `Tribes3-Modded` after opening a PR, after each push or base update, and immediately before merge. Use `gh pr checks <number> -R Tribes3-Modded/<repo>` and confirm the checks belong to the current PR head and target. Wait for pending required checks. If a check fails, read the failing job log, fix and recheck failures within your scope, and record any unresolved check with its run link and next action. Never mark a PR ready or merge while a required check is pending or failing. For paired PRs, verify both sides.

## Live server approval

Commit the source in the relevant repos and verify the push on GitHub first. Then send Chris the issue and commit or PR links, the target server, what would go live, the verification results, and any restart or player impact. Wait for his explicit approval for that deployment before uploading, staging, or applying changes on a live server or restarting it. Follow the approved scope and timing, and record the approval and live verification on the issue.

## Explain every change before it commits

Nobody, human or agent, commits to this repository without explaining the change. These rules apply to every coding tool (Claude Code, Cursor, Grok, Codex, Copilot, Gemini and others) and to people. They match T3BackEndServer's.

How it is enforced:

- `python tools/install_git_hooks.py`, run once per clone, enables `.githooks/commit-msg`. It rejects any commit whose message lacks a subject of 72 characters or fewer, a blank line, and an explanation of at least 15 words saying what changed and why.
- CI applies the same check to every commit a push or pull request adds. Cloud agents that never install the hook are still checked there.
- `tools/agent_commit_guard.py` blocks agent shell commands that would skip the hook, and blocks commits until the hook is installed. Claude Code runs it from `.claude/settings.json` and Cursor from `.cursor/hooks.json`. Gemini CLI, Codex and Copilot have no shell hook here; agents in those tools follow the same rules by instruction.

Steps for any agent before committing:

1. Review what will be committed with `git status` and `git diff --staged`. Stage only the files that belong to this one change; unrelated edits go in their own commit.
2. Explain the change to the user in chat before committing:
   - **What** changed: behaviour first, then the files touched.
   - **Why**: the problem, request or evidence behind it.
   - **Verification**: the exact checks run and their results, and what was not verified. Source checks never prove native gameplay; say so when gameplay is affected.
   - **Risk**: shared contracts, the paired T3BackEndServer checkout, Starter release and deployment impact.
   - **Milestone**: the milestone this advances and what was updated in its file (see "Keep the project and milestones current").

   Commit only when the user asked for a commit. Otherwise stop after the explanation and ask.
3. Write the commit message from that explanation, passing multi-line messages with a heredoc or `-F <file>` rather than opening an editor:

   ```
   <Imperative subject, 72 characters or fewer>

   What: <the behaviour or files this changes>
   Why: <the problem it fixes or the reason it is needed>
   Verification: <checks run and results, or why none apply>

   Milestone: <M-number from project/milestones, or none>
   ```

4. Never bypass the check: no `--no-verify`, `-n` or `-c core.hooksPath=...`. If the hook is not installed, run `python tools/install_git_hooks.py`. If the hook rejects the message, fix the message.
5. Report the commit hash and subject to the user. A commit or push is not a deployment or a Starter release.

## GitHub issues

- When asked what is open, run `python tools/github_issues.py review` and summarise it in chat: urgent and security first, clusters with a likely shared cause, "(host + client)" issues that need both repositories, stale or unassigned issues, and two or three suggested next picks.
- When working on an issue, run `python tools/github_issues.py start N` once. On a branch named `issue-N-short-name`, commits get a `Refs: #N` trailer from `.githooks/prepare-commit-msg`; on a developer branch, put `Refs #N` in the commit yourself. Post `python tools/github_issues.py update N --body "..."` at milestones (root cause, fix pushed, blocked, verification results), put `Fixes #N` or `Refs #N` in the pull request, and run `pause N` when stopping early.
- Comments are public: no secrets, IP addresses, player details, configuration or native logs. Do not close, create or retitle issues unless the user asks.

## Keep the project and milestones current

`project/` is the client's project plan: `project/README.md` describes the project, and each file in `project/milestones/` is one milestone with its goal, "Done when" list, issues and a dated progress log. **Milestone IDs are shared with T3BackEndServer**: M6 here is the client side of the backend's M6, so work that spans both repositories names the same milestone in each. Milestones that only concern the client (M9 onwards) get IDs the backend does not use. This rule binds every harness and person that writes to this repository: Claude Code, Cursor, Grok, Codex, Copilot, Gemini, any other agent, and people.

1. **Read first.** Before starting work, run `python tools/project_milestones.py list` and find the milestone the work belongs to (`python tools/project_milestones.py find N` for issue N).
2. **Update the milestone in the same change.** Any branch that changes code, scripts, runtime Lua, Starter packaging or docs for a milestone also edits that milestone's file before it is pushed for review:
   - add a dated line to its progress log (`python tools/project_milestones.py log M6 "..."`) saying what changed, on which branch or PR, and what was and was not verified;
   - tick an issue only when it is resolved and verified (`python tools/project_milestones.py issue N --done`), and add newly found issues to the right milestone;
   - change the status (`planned`, `in progress`, `blocked`, `done`) or the "Done when" list when they change. A milestone is `done` only when its "Done when" list is met; source checks never prove native gameplay, and a merge, push or Starter build is not a release.
3. **Name the milestone in every commit** with a `Milestone: M6` trailer (`Milestone: M6, M8` for several, `Milestone: none` for work outside every milestone, such as a typo fix). The commit-msg hook rejects commits without it; on an `issue-N-...` branch `.githooks/prepare-commit-msg` adds it when issue N is listed in a milestone.
4. **Update the issues too, when there are any.** The milestone file's issue line and the issue itself are updated together, and every open issue belongs to exactly one milestone. Run `python tools/project_milestones.py audit` to find open issues in no milestone and ticks that disagree with GitHub.
5. **New work, new milestone.** When work fits no milestone, add `project/milestones/M<next>-short-name.md` in the same shape and a row to the table in `project/README.md`, and say so to the user. If the backend has the same kind of work, use its milestone ID instead.

**Merging milestone files.** `python tools/install_git_hooks.py` registers a merge driver (`tools/merge_milestone_file.py`, selected in `.gitattributes`) that keeps both sides' log lines in date order, the later `Updated` date and one line per issue. A real disagreement, such as two different `Status` values, stays a conflict for a person to decide. GitHub's web conflict editor does not run the driver, so resolve milestone conflicts in a local checkout. Never pick one side's progress log.

CI enforces the parts a machine can check: `python tools/project_milestones.py check` validates the files, and `python tools/check_commit_message.py --tracker` fails a branch or pull request whose commits name a milestone whose file the branch never changed. The judgement parts (an honest progress line, issues kept in step) are every agent's responsibility. Report the milestone updates to the user along with the change explanation.

## Checks

Run `python tools/check_source.py` and `python -m unittest discover -s . -p "test_*.py"`. Shared protocol changes must update the paired checkout and shared-contracts.json together; verify with `python tools/check_source.py --peer ../T3BackEndServer`. Never infer native gameplay success from these source checks. Keep game/editor/native qualification isolated and use native_resource_gate.py. Keep secrets, populated connection/configuration files, original game files, large cooked content and native logs outside Git. A Git push is not a deployment.

The public Windows release includes Lobbies, Live matches, Public CTF, and Armor. Put `Start Clan Wars.bat` at the top level of the ZIP. Verify the exact archive with a fresh device profile against the live service before publishing. A Public CTF-only release requires an explicit request.
