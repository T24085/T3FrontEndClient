# Current source changes

2026-11-05: Spectating is limited to first person while third person remains incomplete. The viewer starts in first person, restores it after native perspective toggles, and keeps F5/F6 player switching and F7 first-person reset. F8 third-person selection is removed. Launcher help and generated playtest instructions match this policy. Dynamic and desktop builders now include the canonical spectator runtime when the verified input declares spectator support.

Validation: all 95 discovered unit tests pass under Python 3.13.5, including seven Lua 5.4/candidate-building regression checks. The paired source check parses 57 Python sources and verifies ten shared contracts. Local Tk tests require TCL_LIBRARY and TK_LIBRARY to point at that interpreter's installed tcl8.6 and tk8.6 directories. This is source and synthetic candidate validation; a full player package, native in-game qualification, installed-client update and deployment have not been performed for this change. Existing session-recovery work is separate.

# Baseline status

Imported on 2026-11-04 from the existing community starter project and verified source inventories. The active source catalog contains 22 maps. This import does not rebuild packages, alter desktop shortcuts, restart services, or change a live game.

Release `windows-2026.11.04-r5` uses the complete Windows r5 player package. Every one of its 5,521 declared files passed streamed SHA-256 verification, and its 22 map fingerprints match a fresh read-only verification of the current server. Source catalog helpers now retain all 22 map choices, including the eight native map identities. This verifies distribution integrity and content compatibility, not a repair of the gameplay issues below.

The real-player join failure was reproduced: one admitted player remained on staging team 3 while the other spawned. The local correction is preserved on the backend branch `fix/multiplayer-join-loadouts`; it was not deployed at import time. A corrected isolated native run spawned one medium and one heavy client, but its overall qualification timed out before the match-start check completed. Missing weapon boxes in the armor/loadout menu remain unresolved. Do not describe either issue as fully fixed or deployed.

The direct-port-forwarding friend handoff is experimental and separate. It has transport/source checks, not complete off-site native qualification.

Maps: Damnation, HighOctane, Scarabrae, Stonehenge, Snowblind, Rollercoaster, SnowblindBlizzard, HighOctane2026, Damnation2026, Scarabrae2026, Stonehenge2026, Snowblind2026, SnowblindBlizzard2026, Rollercoaster2026, Torment, DangerousCrossing, Drydock, Katabatic, Wavemist, Hollow, Raindance, Moonrise.
