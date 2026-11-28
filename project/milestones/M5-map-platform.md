# M5: Map platform, audio and environment (client side)

- Status: in progress
- Updated: 2026-11-27
- Target: not set
- Repos: client, backend

## Goal

Maps, their audio, music and environment rules work on the client as the map declares them.

## Done when

- [ ] Map music, splash sounds, saved sound levels and the out-of-bounds warning work in a match.
- [ ] Each issue below is verified in game where it affects gameplay, and closed.

## Issues

- [ ] #39 Bug (still present): saved sound levels not applied on join; sounds play at max until Settings is opened
- [ ] #85 Per-map music hook: play the track named in the map's music field
- [ ] #86 Splash sounds by armor, speed and exit, plus lava (client side of backend #60)
- [ ] #96 Client: out-of-bounds warning and grace countdown (host + client)
- [ ] #102 Map soundtrack helper is blocked by antivirus (hidden PowerShell -EncodedCommand)

## Progress log

- 2026-11-27: Milestone created when the client adopted the backend's milestone structure; lists the open client issues for M5.
