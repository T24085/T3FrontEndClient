# M2: CTF objective parity: flags, turrets, scoring (client side)

- Status: in progress
- Updated: 2026-11-27
- Target: not set
- Repos: client, backend

## Goal

The client shows CTF objectives, flags and scores the way the host reports them, for every player, through joins and leaves.

## Done when

- [ ] Flag, score and generator HUD state agree across clients after joins and leaves.
- [ ] Flag indicators are readable without blocking the view.
- [ ] Each issue below is verified in game where it affects gameplay, and closed.

## Issues

- [ ] #32 HUD sync: scores (and generator icons) inconsistent across clients after joins/leaves (follow-up to #21)
- [ ] #43 Feature request: red border around the team flag icon when the enemy has it
- [ ] #44 Flag indicators are too large: reduce to about 1/4 size and reposition to not block site line

## Progress log

- 2026-11-27: Milestone created when the client adopted the backend's milestone structure; lists the open client issues for M2.
