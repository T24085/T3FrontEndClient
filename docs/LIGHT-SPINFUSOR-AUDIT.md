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

## Moving visual origin follow-up

The reported follow-up is that the disc appears behind the player. The composed `tools/native_disc_visual_probe.lua` observes the original deferred spawn request, projectile birth, collision position, visual root, Niagara component, source character, active muzzle and local camera. It samples through 300 ms and records matching server replicas' hidden/stopped/exploded flags. These are read-only observations of the original projectile. Component transforms do not establish the positions of individual Niagara particles on screen.

External evidence `light-disc-visual-origin-20261104/delay80-r3` passed the native join/probe and original owned-Job cleanup checks, with a rendered owner and a heavy opponent. The byte-preserving loopback gateway measured 80.01-96.09 ms of added delay per direction, with no configured jitter/loss model. The owner fired while stationary, forward at 50 m/s and laterally at 50 m/s. Each local request and projectile birth had the same game timestamp. The local firing origin matched camera X/Y, with a 2 cm vertical offset. In the sampled unimpacted moving shots, the visual component was at least 43.38 cm ahead of the camera along the fixture's fixed +X firing direction, rather than behind it. All 14 server replica samples that were still in flight were hidden for the owning client. Old stopped/exploded objects must be excluded from duplicate-projectile counts.

This controlled run did not reproduce an owner-camera visual-origin delay. It does not close the actual skiing/turning or off-site symptom. Original zero lateral inheritance means a sideways-moving player naturally travels away from the fired disc's lateral position; this is a possible perceptual explanation, not a verified diagnosis of the report.

The first rendered tap also generated an extra local prediction that was absent on the authoritative server. An incomplete Windows mouse-input run (`delay80-manual-r5`) observed the same first-shot discrepancy and only one authoritative shot/one settled round used. It did not capture the required moving shots, so it is not a passing manual qualification or proof of a renewed double-shot gameplay bug. Direct native C++ input did not traverse the probe's reflected Press/Release hooks; absent hook records cannot establish absent physical input. Reflection enumeration has since been moved before firing to reduce measurement overhead, and the manual airborne window has been extended.

The reduced-overhead Windows mouse-input follow-up (`delay80-manual-r6`) captured three clicks, three local predictions and three authoritative projectiles with matching prediction IDs 1/2/3. The earlier extra prediction did not recur; its cause is unproven and should not be attributed to production gameplay from these instrumented runs. The forward shot had source velocity `(5000, 0, -8000)` cm/s: 50 m/s forward while falling. Its visible root at birth exactly matched the current active muzzle, 43.27566 cm ahead of camera X, and remained ahead throughout the 12 sampled poses. Local request and birth again shared a game timestamp. The intended lateral click occurred after landing, so only the forward moving mouse shot is established. The run was deliberately cancelled through its original host owner, retained `passed=false`, and all five original owned Jobs emptied. Teardown reported a gateway connection reset after the requested host stop. Gateway scheduling also had startup stalls up to 875 ms, so this run is not a fixed-160-ms RTT performance qualification. No production behavior was changed or deployed.

To reproduce the diagnostic with the backend qualifier, add these options to the usual verified external content/game/workspace arguments:

```powershell
--blue-loadout 527 --render-client 0 --delay-ms 80 --manual-probe-input --review-seconds 30 --native-probe <frontend-checkout>/tools/native_disc_visual_probe.lua --probe-base <frontend-checkout>/tools/native_disc_speed_probe.lua
```

Without `--manual-probe-input`, the diagnostic uses controlled native ASC taps. Manual mode generates no firing inputs; use the rendered native viewport and allow the original reload between clicks. Both modes move only the isolated test character and leave projectile properties, ammo and weapon cooldowns native. Detailed evidence, decoded original assets and game binaries remain outside source control.
