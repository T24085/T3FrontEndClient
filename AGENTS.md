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
- Use a temporary branch for each change. When its PR merges, verify that GitHub removed the head branch. If the branch remains, check the latest remote tip, confirm its work reached the intended target and check for open PRs using it as a head or base. Remove the remote branch once those checks pass. A matching merged PR head plus its integration commit in the target also verifies a squash merge.
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

Run `python tools/check_source.py` and `python -m unittest discover -s . -p "test_*.py"`. Shared protocol changes must update the paired checkout and shared-contracts.json together; verify with `python tools/check_source.py --peer ../T3BackEndServer`. Never infer native gameplay success from these source checks. Keep game/editor/native qualification isolated and use native_resource_gate.py. Keep secrets, populated connection/configuration files, original game files, large cooked content and native logs outside Git. A Git push is not a deployment.

The public Windows release includes Lobbies, Live matches, Public CTF, and Armor. Put `Start Clan Wars.bat` at the top level of the ZIP. Verify the exact archive with a fresh device profile against the live service before publishing. A Public CTF-only release requires an explicit request.
