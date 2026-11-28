# T3FrontEndClient project plan

The client side of TRIBES 3 Clan Wars: the Starter, the in-game client runtime and Starter releases. The paired server work is planned in T3BackEndServer's `project/`.

Milestone IDs are **shared with T3BackEndServer**, so a milestone such as M6 (lobby and match control) means the same work in both repositories. Client-only milestones (M9 onwards) use IDs the backend does not. The rules for keeping this plan current are in `AGENTS.md`, "Keep the project and milestones current".

| Milestone | Title |
|---|---|
| [M0](milestones/M0-engineering-workflow.md) | Engineering workflow, releases and repository hygiene |
| [M2](milestones/M2-ctf-objective-parity.md) | CTF objective parity: flags, turrets, scoring (client side) |
| [M3](milestones/M3-combat-and-movement.md) | Combat, abilities, movement and spawns (client side) |
| [M4](milestones/M4-sensors-and-minimap.md) | Sensors, radar and minimap (client side) |
| [M5](milestones/M5-map-platform.md) | Map platform, audio and environment (client side) |
| [M6](milestones/M6-lobby-and-match-control.md) | Lobby and match control (client side) |
| [M8](milestones/M8-hosting-and-environments.md) | Self-hosting, local play and environments (client side) |
| [M9](milestones/M9-bot-training.md) | Bots and training tools |

Use `python tools/project_milestones.py list` for status and counts, and `python tools/project_milestones.py audit` to compare with GitHub.
