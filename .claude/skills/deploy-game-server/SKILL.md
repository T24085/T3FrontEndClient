---
name: deploy-game-server
description: Use when taking a TRIBES 3 change through PR review, preparing a release for GameServer01 or another production game server, or verifying an approved rollout.
---

# Merge and deploy a production release

Read the workspace `PROJECT_KNOWLEDGE.md` if available and the current GitHub `main` copy of `AGENTS.md` and `docs/STATUS.md` in each affected repository. The canonical organization is `Tribes3-Modded`. T3BackEndServer owns the host, T3FrontEndClient owns Starter and its update feeds, and Tribes3MapTool owns authoring tools. A Map Tool merge only needs a game server release when the approved change also includes deployable map content, a host catalog change, or runtime changes. Use the owning repo's map intake, cook and manifest workflow for map outputs.

## From topic branch to reviewed main

1. Check issue queues, open PR heads and bases, and shared contracts. Claim the issue and record scope, owner and Central start time. Start an isolated `issue-N-short-name` worktree from canonical `main`. Use a fork if your permissions require it.
2. Reproduce the issue, run the affected repositories' checks, and qualify native behavior separately when affected. Keep native jobs under the cooperative resource gate. Install repository hooks where present, review the staged diff, explain the change and verification to Chris, and follow the repo's milestone and commit-trailer rules.
3. Push the topic branch and open a PR. For paired or stacked changes, link the PRs, name the intended merge and release order, merge prerequisites first, then retarget and reverify dependents against their current bases. An independent `T3-Mod-Admins` reviewer approves and an admin merges. Follow repository rules on who may merge and use GitHub PRs for all changes to `main`.
4. Fetch canonical `main` and verify the reviewed code landed. Pin each source SHA to a commit reachable from its corresponding `main`. After merge, confirm the topic branch was removed or record the open dependency or unmerged work keeping it. Keep rollout issues open through live verification.

## Prepare the exact release and get approval

1. Build from clean checkouts of the pinned `main` SHAs. Every production upload, staging operation, hotfix and rollback must come from verified canonical `main` provenance. Stop if provenance is unclear. Package locally with the maintained release tools appropriate to the change. Preserve operator settings, current map assets and intervening fixes. Record the package manifest, hashes and test evidence. Use the [backend release guide](https://github.com/Tribes3-Modded/T3BackEndServer/blob/main/docs/DEVELOPMENT.md) and [Starter signing and publication guide](https://github.com/Tribes3-Modded/T3FrontEndClient/blob/main/docs/STARTER_UPDATES.md) where relevant.
2. Verify the target's current running revision or file inventory and, for a Starter release, the preceding signed indexes. Identify drift and account for each affected file. Establish an operator-controlled rollback with verified `main` provenance and the previous signed indexes as applicable.
3. Ask Chris for explicit approval for the exact target, PRs and SHAs, package hashes, feed changes, test evidence, restart and player impact, window, and rollback plan. Include rollback authorization in the approved scope if needed. Wait for approval before any live upload, staging, apply, publish, or restart. If the approved inputs or scope change, stop and reconfirm.

## Activate and verify the approved release

1. On GameServer01, use the operator's current authenticated SSH/SFTP workflow for staging and the existing desktop-session activation task for restarts. Retrieve the current operator runbook and controls through the private handoff. For another production host use its verified equivalent. Recheck the live parent, package hashes and approved room-drain conditions before activation. If the parent changed or the approved window closed, stop.
2. Save the affected files, inventory, settings and feed indexes needed for recovery. Cooperatively stop the owned service, apply the staged package only within the approved scope, and restart it through the operator control. Preserve process and Job ownership. For paired releases, use the approved compatibility order. Publish signed feed indexes after their referenced content is present and verified, and after any required host readiness check.
3. Read back deployed hashes and confirm lobby readiness over the configured TLS endpoint. Verify the expected catalog, capabilities and allocation paths affected by the release. Start a representative native match, confirm it reaches native ready, and clean up the test match. Retest the reported behavior and verify signatures and downloads for each changed feed. If verification fails, halt additional publication and follow the approved recovery plan or ask for authorization.
4. Record the deployed SHAs, package identity, feed versions, approval, availability and issue-specific results. Keep sensitive host settings and raw logs in private operator storage. Close an issue only once its reported behavior is verified live and repository closure authorization is satisfied. Record remaining symptoms and the next action on its issue.
