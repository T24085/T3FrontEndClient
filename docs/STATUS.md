# Baseline status

Imported on 2026-11-04 from the existing community starter project and verified source inventories. The active source catalog contains 22 maps. This import does not rebuild packages, alter desktop shortcuts, restart services, or change a live game.

Release `windows-2026.11.04-r5` uses the complete Windows r5 player package. Every one of its 5,521 declared files passed streamed SHA-256 verification, and its 22 map fingerprints match a fresh read-only verification of the current server. Source catalog helpers now retain all 22 map choices, including the eight native map identities. This verifies distribution integrity and content compatibility, not a repair of the gameplay issues below.

An admitted player could remain on native staging team 3 while another player spawned. The backend correction is on `fix/multiplayer-join-loadouts` and was installed and activated on the laptop server on 2026-11-04. Readback verified its exact runtime hash, unchanged map fingerprints, all 22 maps and the configured capacity of 10 simultaneous matches. This does not claim ten populated matches were stress-tested.

Fresh isolated native qualifications now observe the staging-team transition, both medium (529) and heavy (531) players spawning, the original match clock advancing, and all five original owned Jobs empty after cleanup. A separate rendered loopback run showed weapon icons and names for light, medium and heavy armor; selecting the original Thumper option updated the menu and the menu returned to gameplay. The earlier 85-second timeout is superseded. These are bounded loopback results, not off-site multiplayer or full-match qualification. The intermittent double-fire report remains unreproduced; the existing weapon-switch input fix is already present in the imported frontend.

The direct-port-forwarding friend handoff is experimental and separate. It has transport/source checks, not complete off-site native qualification.

Maps: Damnation, HighOctane, Scarabrae, Stonehenge, Snowblind, Rollercoaster, SnowblindBlizzard, HighOctane2026, Damnation2026, Scarabrae2026, Stonehenge2026, Snowblind2026, SnowblindBlizzard2026, Rollercoaster2026, Torment, DangerousCrossing, Drydock, Katabatic, Wavemist, Hollow, Raindance, Moonrise.
