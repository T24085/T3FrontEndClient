# Light Spinfusor speed audit

The reported symptom is that the Light Spinfusor feels off mostly while moving. The 2026-11-04 audit found no physical launch-speed or directional-inheritance mismatch in the bounded native loopback test. It does not close the reported moving-only feel issue or qualify off-site visual prediction.

Fresh read-only extraction and decode of the original Steam `BP_Projectile_Topaz_LightSpinfusor` package found `InitialSpeed=13500` and `MaxSpeed=27000`, in centimeters per second: **135 m/s launch speed**, capped at **270 m/s**. Native class defaults on both client and host reported forward inheritance `1.0`, lateral inheritance `0.0`, and zero projectile gravity. The source audit found no production projectile-speed/velocity assignments. Installed client Lua matched source SHA-256 `daf01e9ab75df816c2d92ce50ce0b5d4b823b7a88102ba83774b7ead4d87668b`; live server Lua readback matched tested source `9074833e9f28477bff8c86c4b86670b10b6d8d566c66529d51cc3fee7bae7022`.

Evidence `light-spinfusor-parity-20261104/native-r3` observed three stationary shots and two moving shots through the original granted light loadout 527, with an original heavy player as the other team. The private authoritative fixture teleported only that test character above the terrain and used native `LaunchCharacter` at 5000 cm/s, first forward and then laterally. Original weapon inputs, ammo, reload, projectile creation and projectile properties remained native. This is controlled character motion rather than a skiing-route playtest.

| Character motion | Client disc launch speed | Server disc launch speed |
| --- | ---: | ---: |
| Stationary | 135.000 m/s | 135.000 m/s |
| Forward at 50 m/s | 185.001 m/s | 185.001 m/s |
| Sideways at 50 m/s | 135.025 m/s | 135.025 m/s |

The sideways shot's small increase matches the small projection of character velocity along its actual firing direction. Both roles matched the original forward-only inheritance formula. All eight airborne trajectory samples per role also matched the launch speed within the analyzer's 0.25 m/s bound. Later stationary samples are excluded from clear-flight assertions because those shots can hit existing geometry. The native match clock advanced, source pins stayed unchanged, and all five original owned Jobs reported zero remaining processes.

Earlier evidence is retained separately: `native-r1` verified stationary speed but produced no useful movement at firing instants; `native-r2` failed because the moving request arrived before reload completed. Neither establishes moving parity. The corrected `native-r3` timing leaves a full three-second interval between shots.

Run the backend's `tools/qualify_multiplayer_join.py` with the usual external verified content/game/workspace arguments plus:

```powershell
--blue-loadout 527 --native-probe <frontend-checkout>/tools/native_disc_speed_probe.lua
```

Then analyze the fresh external evidence:

```powershell
python tools/analyze_disc_speed.py <external-native-evidence>
```

The analyzer requires a passing native proof, empty owned Jobs, three stationary and both actually moving shots per role, matching original defaults, and matching airborne travel. Focused analysis tests reject stationary-only coverage, lost forward inheritance, incorrect airborne travel and swapped role evidence. No gameplay settings or deployed packages were changed by this audit.
