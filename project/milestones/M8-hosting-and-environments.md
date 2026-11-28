# M8: Self-hosting, local play and environments (client side)

- Status: in progress
- Updated: 2026-11-28
- Target: not set
- Repos: client, backend

## Goal

Players can host and join locally, Starter updates stay verified, and development, test and production stay apart.

## Done when

- [ ] Local play works from the Starter.
- [ ] Starter updates stay on the verified sync path.
- [ ] Development, test and production Starters run side by side without affecting each other.
- [ ] Each issue below is verified in game where it affects gameplay, and closed.

## Issues

- [ ] #78 Local play: start a local host from Starter and join it from the server list
- [ ] #89 Keep signed Starter releases on the verified per-map sync path
- [ ] #123 Starter: environment-aware installs (development, test, production) with separate feeds and servers

## Progress log

- 2026-11-27: Milestone created when the client adopted the backend's milestone structure; lists the open client issues for M8.
- 2026-11-28: `feat/regional-server-picker` adds server selection in Windows and Linux Starter using the configured coordinator directory and host-bound enrollment (Tribes3-Modded/T3BackEndServer#23). The selected host owns the browser, lobby and match connection. Live regional gameplay remains pending.
- 2026-11-28: Branch issue-23-atlanta-default selects the listed, enrolled Atlanta server when the Clan Wars Windows and Ubuntu Starter open, so Create Lobby starts there. GameServer01 remains available through the selector and on fallback. Direct Hosting tests covered Create Lobby routing and fallback, and the live directory returned Atlanta. Native join and signed feed rollout remain pending.
