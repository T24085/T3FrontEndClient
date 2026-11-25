# Small-screen Play lobby

The Play lobby keeps team rosters side by side, groups match setup fields, and keeps the match actions visible at the bottom. Join and create fields collapse while a lobby is active. Supported lobby options such as spectators, bots, and flag indicators are available under **Advanced rules**. At narrower widths, fields and secondary match actions can wrap while preserving their enabled states. See frontend issue #72.

# Blink cue timing

The owning client applies the authoritative Blink movement and presents one
departure and one arrival. The arrival cue and first-person flash wait for
the movement to reach the player. Nearby observers still receive the native
host cues. The fix for duplicate cues is tracked in frontend issue #60.

# Private-match fall damage

Starter shows **Fall damage** beside **Flag indicators** when a host
advertises the rule. The lobby leader can change it while setting up the
match, and the lobby reads back the host's selection. It defaults to off.
Damage is calculated and applied by the host. This client candidate remains local.

# Spectator camera modes

The client also applies the body presentation and ski-label repair when the
native death camera follows another player. This path leaves the view target,
input, AFK policy, and respawn under native control. It restores presentation
when the player respawns or the remote view ends.

Spectators start with the chase camera. In open space the camera sits 5.8 m
from a raised pivot and looks down at a steady angle. A world-static sweep
selects a raised or shoulder angle when a nearby wall blocks the usual view.
The client writes the resulting pose directly to the camera because the
spring arm socket can retain its initial position on a remote actor. Left
click selects the next player and right click selects the
previous player. F7 selects first person, F8 selects chase, and middle click
switches between them. Explicit perspective keys also refresh a cached camera
when the controller already reports the requested mode. The selected perspective
persists across target changes and respawns.
The spectator follows native mesh and material replacements and refreshes
cosmetic overrides that arrive on the original material after the view opens.
The observer HUD also suppresses the default “Text Block” beside “SKI TOGGLE”
and restores the label when the native HUD supplies a value.

First person follows the viewed player's native eye position and field of view
and takes its rotation from the player's replicated aim. When the native
spectator pawn or view is briefly unavailable, the client waits for it and
re-enters the selected perspective once it is ready. This preserves the
spectator-only camera scope.

The signed Windows r93 and Linux r25 builds contain the earlier collision
boom. This candidate carries the newer chase camera and the first-person
and transition fixes. The isolated Unreal fixture confirmed the eye position,
aim, and field of view, and checked that the chase camera clears static
obstacles and ignores dynamic blockers. The Lua fixture covers transient
spectator state and perspective changes. A rendered multiplayer check and
Starter publication are pending. See frontend issue #76.

# Friendly flag carry border

The CTF score bar draws a red border around the local team's flag icon while
a living opponent carries it. The border clears when the flag detaches or
returns home. It follows the current native HUD icon after a rebuild.

# Community map lighting

The client reduces the ambient skylight on the current cooked Minotaur,
Beggar's Run TWL and Quagmire TWL 2026 maps. Quagmire also uses lighter fog
starting 30 meters out. The change uses the loaded map's sky and fog actors.
Base fixtures, emergency lighting, and the weapon materials retain their
authored settings. A rebuild that changes the tuned properties takes precedence.
The adjustment is a local candidate pending a rendered in-game comparison.

# Community minimap capture

Starter matches the loaded level against the community package path. The
capture uses the loaded `ValWorldSettings.MapSize` for its orthographic width
and calls the original widget to use that same scale for markers and zoom.
Same-world cooked meshes from the map's asset group set camera height and
clipping. Maps that already provide a capture use it normally.

The background is captured as soon as the HUD texture is bound. Radar icons
can attach later when both native sensors are available. Regression tests
exercise generated catalog rows for Kata, Minotaur, Beggar's Run and Quagmire,
plus retail and authored-capture controls. This is a local client candidate.
Rendered minimap verification is pending.

# Client staging cleanup

Starter retires the private `game` folder when a session's owned Job reports zero
processes. It also retires cancelled or replaced preparations and descriptors
whose join was abandoned before launch. Session logs, saved profiles, the game
install, and shared caches stay in place. A Job without a confirmed empty state
keeps its staging data for investigation.

Run `python tools/cleanup_client_sessions.py --workspace <workspace> --package
<installed-Starter>` for a dry run of historical cleanup. Add `--apply` with
Starter closed to reclaim expired payloads with confirmed terminal Job records.
The command keeps the evidence and reports how many payloads need manual review.

# Map-local weather

The Direct Starter requests verified `lua/<MapId>/objectives.lua` descriptors
with its map inventory. A weather-only edit refreshes the cached revision before
joining, even when the cooked files are identical. The private catalog uses the
selected map and the public catalog prepares weather for map rotation. Omitted
weather uses the existing built-in Lua default. Explicit `weather=false` opts out
of scripted weather. Older hosts can still use descriptors from a full archive.

`lua/weather.lua` animates cooked cosmetic actors for snow, sand, rain, ash
and wind. Set `weather` on the table returned by `descriptor(row)` or on the
top level of a format-1 placement file. Supply `kind` and an ordered
`actors` list with zero-based indices. Optional `density` is the active
fraction (0 to 1), `speed` is in cm/s, and `wind={x,y}` sets world-space
horizontal velocities in cm/s. `tint` and its original alias `color` accept
three linear RGB values (0 to 1) for the cooked material's `WeatherColor`
parameter. Rain and ash need their own cooked meshes or materials.

For rooms and tunnels, add `exclusions={{center_cm={100,-200,250},
half_cm={500,800,300},yaw=90}}` to `weather`. Supply up to 16 boxes with
world-space centers, positive half extents along the box's local axes, and
yaw in degrees about world Z. Each enabled mesh receives the vector
parameters `WeatherBox1_Center`, `WeatherBox1_Half`, and
`WeatherBox1_Axis`, continuing through `WeatherBox16`. `Axis` is the box's
local X direction in world space. The material masks each flake against the
boxes in world space. Author unused slots with zero half extents and ignore
them in the material. The runtime writes the box parameters once at setup.

For the optional whole-weather fade, set `fade_when_camera_inside=true`
and have the material apply its scalar `WeatherOpacity` (default `1`).
The client fades between `1` and `0` in about half a second as the camera
leaves or enters an exclusion. This also fades visible outdoor weather
while the camera is indoors. Use the box mask alone to keep snow visible
outside doors and windows.

For local lighting, set `lighting={actors={"StormLight"},intensity=2500}`
with the names of cooked, movable, non-replicated PointLights and the
intensity in each light's authored units. Use `kind="lighting"` for a
lighting-only descriptor with no particle actors. The source retains
`snowblind_weather.lua` as a compatibility stub. Packages targeting a host
that still fingerprints the original weather file preserve those bytes and
load `weather.lua` for the newer client.

The Windows and Steam Proton wrapper accepts a verified host objectives
snapshot through `--map-objectives`. These descriptors are shipped as
inventoried client files, outside the cooked-map download feed. The signed
Direct Starter release can also stage the tested weather runtime and
Katabatic T2 descriptor in the owned session directory. A signed runtime
takes precedence over the archive's runtime. Verified packaged map descriptors
take precedence over fallback descriptors, including an explicit opt-out.

# Native flag widget callback

Both original flag widgets require the flag actor, current holder info and
previous holder info in OnFlagHeldChanged. The decoded handlers read only
the current holder info. The optional HUD pulse now supplies all three
arguments. A regression checks both callbacks during flag return.

A rendered client with this local candidate processed both at-home flag
states without an optional marker error in a private High Octane 2026
match on GameServer01. The same client received one initialized bot per
team, and both moved. The test ended with its room closed and its Job
empty. The flags stayed home, so this run did not exercise a projected
pickup or toss marker. This client candidate has not been published.

# Flag indicator return reset

The enabled marker now reads the native `HolderInfo.bReturned` flag and
passes return transitions through the original widget's
`OnFlagHeldChanged` handler. The retail Blueprint caches that struct,
clears its return timer and hides the moving objective when returned.
Its Tick also stops tracking a returned flag. The custom pulse now honors
that visibility and ignores a stale holder while the return is replicated.
The original stationary base widgets receive the same flag-state update,
restoring their native home labels from the flag's returned state.

The return regression covers both team flags, delayed owner/movement
cleanup, timer reset, repeated pulses and the next pickup and toss. The
previous implementation fails the same regression. All 187 client tests
pass with seven skipped, and the source check verifies 14 shared contracts.
Signed Direct Starter revision 19 is published on GameServer01. The live
HTTPS index signature and all seven payload hashes were verified. A
disposable copy of the installed revision 18 updated to revision 19
through the live feed, changing only the flag HUD Lua and its inventory.
Live rendered qualification is pending.
The decoded retail widget used for the comparison is retained outside Git
under `verification/flag-indicator-motion-20261028/widget-functions.json`.
The companion base widget decoding and review are under
`verification/flag-indicator-return-20261110/`.

# Community flag indicators and radar scale

The enabled flag indicators follow the replicated flag or carrier from the
client HUD tick. A carried flag uses the native owner or attachment to
distinguish active possession from the old holder that can remain after a
toss. A zero-size native flag canvas uses viewport DPI for placement.

The radar uses the same world width for the scene capture and the original
map widget's projection. Widths come from the playable bounds of 15
community maps, rounded up with ten percent padding about the map origin.
Damnation 2026 uses 155,000 cm. The native zoom, sensor power, and spotting
behavior remain under the original game. Maps without surveyed bounds use
the authored width.

An isolated rendered Damnation 2026 client projected both flag widgets,
bound both radar sensors, and reported a 155,000 cm projection width at
native zoom 1.0. A pickup and toss regression test covers the stale holder.
The signed Direct Starter update is revision 17. It adds radar capture and
sensor binding for the catalog entry for Katabatic T2 2026. A rendered match
used the map's authored 190,000 cm width at native zoom 1.0, projected both
flags, and received one classified bot on each team. The live update index
and Lua payload passed HTTPS verification.

Connected client checks covered all eight 2026 entries in the live catalog.
Each projected both flag markers and used its map-specific radar width at
native zoom 1.0. Damnation and Katabatic T2 ran with rendering enabled.
The remaining maps ran headlessly. Seven maps replicated one bot per team
to the connected client. Rollercoaster lost its live connection after the
HUD checks, then an isolated host using the deployed bot rules confirmed
one classified bot per team.

# Linux Proton r12

The Linux package is built from the published Windows r12 archive and bundles the 22 current map fingerprints from the approved host. The Proton bridge gives the shared Starter and signed updater the Linux CA context and keeps the existing Steam command and owned-process preflight. Steam/Proton multiplayer and Steam Deck Gaming Mode require separate gameplay qualification.

# Windows r12 automatic updates

The Windows Starter checks the signed r12 update channel before loading its desktop modules. The channel can update supported Starter modules and community gameplay Lua. The existing map catalog handles cooked map files, and Steam handles the original game.

The bootstrap verifies an expiry, revision, Windows CNG signature and individual file hashes. It downloads only differing files and holds a folder lock for the lifetime of the desktop app. Interrupted installs and startup failures restore the prior files from the update journal. See [publishing Starter updates](STARTER_UPDATES.md).

# Flag toss release position

The player client seeds the detached flag from its first replicated movement update. The visible flag and its local collision use the same actor root. The handoff applies once after detachment and preserves the server's toss, hit and bounce behavior.

In an isolated Katabatic toss, the baseline proxy started 107.83 cm from its first server position. With the correction, the proxy matched that update in the release frame. All 150 client tests and 13 shared contract checks passed, and all three owned native Jobs finished empty. The loopback client received later movement updates in a burst. Rendered flight and bounce shots during a live match still need a player retest. Native evidence is under `verification/flag-flight-snap-20261108` outside Git.

# Windows r11 host map catalog

Starter reads the approved host’s advertised map IDs and labels. The host can add compatible cooked CTF maps with the current client runtime. The downloaded revision binds the new level definition to its verified inventory before the isolated client selects the level. The starter continues to use the r10 download protocol when connected to an older host.

# Windows r10 map syncing

The Starter checks the connected lobby's map inventory in the background. Existing bundled and cached bytes are reused by SHA-256. A join compares the server's match fingerprint with the available revision and sends the selected revision through the existing owned preparer. A downloaded revision only supplies cooked map files to the isolated game directory. Lua, binaries, the Steam installation and the distributed client files stay outside map syncing. A changed map requiring new runtime or base-game files still needs a client release.

# Post-match Escape candidate - 2026-11-06

The original in-map results widget owns both the final scoreboard and summary tabs. Its original `OnNavigateMenu` action requests the stock `StartMenu` when `Result` is the top route. The private player runtime adds a fallback for Escape only on that owned, visible results widget after the replicated gameplay-ended phase. It defers to the stock handler, skips other routes and ignores the Escape that just closed the original menu. It does not change the desktop launcher.

Private revision `post-match-escape-20261106-r1` is installed on the local community client with a rollback backup. The installed Lua matches the source and preserves the latest Heavy Bolt trail update. All 139 client tests and 12 paired source contracts passed. In an isolated original Katabatic match, the registered fallback callback opened `StartMenu` on the actual final summary. The subsequent close fixture stopped at its Blueprint reflection check. Physical Escape and closing in the rendered game still need a player retest. The paired live server now preserves the original results phase. The stock retail install and public download are outside this activation. Evidence is outside Git at `verification/post-match-escape-20261106/deployment/VERIFICATION.json`.

# Heavy Bolt whiteout follow-up - 2026-11-06

The user's recording shows a large cyan effect covering the view after firing Heavy Bolt and switching weapons. The running client's Lua and event markers confirm the previous stowed-trail correction was loaded; the earlier component-state qualification did not establish that the visible whiteout was fixed.

The private `fix/heavy-bolt-whiteout-r2` candidate excludes stopped/unknown-state projectiles, resets inherited first-person Niagara override parameters when selecting the original world-space trail, and changes each observed live projectile only once. It retains the existing exact local-player, weapon, world and component-owner guards and does not change projectile physics, damage or ammo. These are plausible unguarded cases identified from the clip and original Blueprint inspection, not a confirmed visible root cause.

Validation: all 125 client tests and paired source checks pass, including stopped-effect exclusion, override reset, native asset revisit, new-flight state cleanup, input-release isolation and canonical embedded Lua checks. No native game was launched or stopped for this follow-up. Visual confirmation, installed activation and public release updates remain separate and pending; r7 still contains the previous candidate.

# Flag toss aim server update active - 2026-11-06

The current client passed the pinned-TLS readiness check against private host revision `flag-toss-aim-20261106-r1`. The host supplies the player's aim to the original flag toss. All 134 client and 136 backend tests pass. Grounded toss flight remains for in-game verification.

# All-three Chaingun private server candidate active - 2026-11-06

Private server revision `turret-damage-chain-candidate-20261106-r2` is active after the user's authorized restart. It covers original Light, Medium and Heavy Chaingun main abilities. The existing installed client passes the pinned-TLS readiness check against the fresh server; no download/runtime change is required. All 134 client and 127 backend source tests pass. Sustained incoming damage and actual enemy tracer rendering remain for the user's gameplay test.
# Observation turret capture diagnostic follow-up - 2026-11-06

The test-only repair fixture releases its original input as soon as captured ownership replicates. The paired native Katabatic baseline completed capture and release while both observation turrets still had zero grants. The server's host-only correction verified both original guns equipped; enemy-player fire remains unverified. No client runtime or public release changes. All 134 client tests and paired source checks pass.

# Light / Medium / Heavy Chaingun server extension - 2026-11-06

The paired private server candidate now covers the original Light Chaingun, Medium Chaingun and Heavy Chain Cannon main abilities with the same ownership guards. This requires no player runtime or download change. The user will test sustained damage and opposing-view tracers; no additional native game was launched for this follow-up. Backend source validation passes 127 tests and paired contracts are unchanged.

# Paired private server candidate ready for user testing - 2026-11-06

The paired laptop server now runs private candidate `turret-damage-chain-candidate-20261106-r1`, preserving its latest repair-capture and onboarding fixes. The current installed client passed the pinned-TLS readiness check against the restarted service; no client Lua or release was replaced by this task. All 134 client tests and 126 paired backend tests pass. The user will perform the turret gameplay tests. Incoming damage and opposing Medium Chaingun tracer appearance remain unverified candidates; see the paired backend deployment record. Original game assets, keys, populated settings and native logs remain outside Git.

# Foreign Chaingun delivery observations - 2026-11-06

The private incoming-damage fixture now includes an exact foreign-source native projectile/cue observer, including OnRep events, the actual Niagara trail asset and its visibility fields. Five focused observer simulations and all 134 client tests pass; paired source checks pass. The actual Heavy Gladiator item and mortar secondary slot replace incorrect diagnostic selections. No player runtime was modified. The paired server has a narrow Medium Chaingun prediction-branch candidate awaiting the native comparison; an original host-only inspection confirmed its authored 3P trail and enabled replication defaults, but does not establish peer rendering. Further native launches are paused for the user's Bolt white-screen comparison. No installed client or release was updated.

# Incoming turret damage and tracer diagnostics - 2026-11-06

`fix/turret-damage-chain-visuals` preserves current server-access onboarding and personal-turret diagnostics, adding a private original-input fixture for the paired incoming-damage investigation. It requests original loadout items, verifies the selected native weapon, and records original projectile/trail events. It does not change player Lua runtime, replay effects, grant weapons or establish rendered enemy tracer visibility. All 129 client tests and paired source checks pass. Native incoming-damage results are unresolved; two flight runs stopped at the existing live memory reserve with original Job cleanup confirmed. No installed client or public release was updated. The paired backend's `docs/TURRET_RECEIVE_INVESTIGATION.md` records the candidate, negative evidence and remaining qualification.
# Repair-tool capture diagnostic - 2026-11-06

`diagnostic/retail-center-capture` adds a test-only original repair-tool input fixture for the paired backend Katabatic center fix. It waits for the isolated owned player to be positioned, aims at the original point collision component, selects the original repair slot, discovers the original ability input and presses/releases it. No client runtime, grant, healing or production input behavior changes. A native Heavy-client run observed original InputID 33 and a native four-second neutral-to-blue capture. Its overall harness did not pass: the live-memory reserve stopped it after capture before input-release completion, with all three original Jobs empty. Other teams/maps, recapture and cross-PC behavior remain unqualified. All 129 client tests and paired source checks pass. Public r7 and installed clients are unchanged by this diagnostic source. Additional native tests are paused for the user's Bolt work.

# Automatic server-access setup - 2026-11-06

`feat/tailscale-server-access` adds an optional **Set up server access** window: install/sign into Tailscale, obtain and accept a server-sharing invitation through a public HTTPS bootstrap, then check the existing pinned-TLS lobby connection. Setup work has its own queue and does not clear foreground lobby operations. The paired broker automates device-sharing invitations without adding tailnet members. Only a three-field player bootstrap enters client packages; API tokens and operator/cache files are excluded. New runtime modules are included by the dynamic, desktop and complete-release builders; configured builds accept `--server-access`.

Validation: all 129 client tests and paired source checks pass, including Tk setup controls, TLS/redirect/destination rejection, credential separation and real fixture-ZIP bootstrap inventory/hash audits. Public builds omit the enrollment code and prompt for the one shared playtest code; private builds can preconfigure it.

Private activation is complete: the desktop-shortcut package received only the launcher, two setup modules, player bootstrap and its inventory, with an original-file backup and all 22 map fingerprints/other inventory rows preserved. Its actual bundled Python obtained a real server invitation and connected to the pinned-TLS lobby. Reopen Starter to load the new button. The separate public browser setup page also works with existing r7 clients, so friends do not need a new client release for onboarding: share its stable URL and the one playtest code privately with the group. Provider-backed public-IP HTTPS checks passed the landing page, authorization rejection, API invitation and browser redirect; an external person's actual acceptance and subsequent gameplay remain unverified. r7 and Drive archives are unchanged. The empty lobby was restarted cooperatively through its existing desktop task to activate accepted-share admission; no native game was launched or player interrupted. Evidence is outside Git in `verification/tailscale-onboarding-20261106`.
# Personal turret diagnostic fixture - 2026-11-06

On `fix/personal-turret-fire`, `tools/native_personal_turret.lua` is a development-only original Medium inventory/pack-input fixture for the paired server investigation. It is not included in player runtime or the existing r7 release. Client gameplay source is unchanged; all 121 tests and paired source checks pass. The paired server's isolated two-client original Katabatic run passed original Medium Technician (530) / pack 19 deployment, friendly-only no-fire and enemy targeting/firing with 525 damage while other AI controllers were disabled. All original Jobs ended at zero, with no test mesh override. Other maps, moving targets and cross-PC latency were not qualified; no new client package was published.

# Complete client r7 published

The [2026-11-06 complete r7 playtest release](https://github.com/T24085/T3FrontEndClient/releases/tag/windows-2026.11.06-r7) is public. Its 1,445,723,086-byte ZIP retains the frozen cooked maps and portable/native binaries from the SHA256-pinned r6 parent while overlaying current canonical client source, including `lua/client.lua`. All 5,522 declared files passed streamed SHA256 checks and all 22 map fingerprints match a fresh read of the current server. The exact extracted package passed bundled Python/Tk/control smoke checks, with its original owned Job empty. The included client Lua matches the byte hash used in the Heavy Bolt native firing/stowing run. All 121 release-source tests and paired source checks pass.

All six uploaded asset digests/sizes match locally. The public unauthenticated download returned HTTP 200 with the expected size and ZIP signature, and the public checksum matches. Release source is frontend `9774cd61c61881bb20c5c293c71031e37383c888` with backend reference `09ae7ae52202de365ae091843ceeaf44e9157011`. Visible whiteout confirmation remains pending and is explicitly documented; no additional native game was launched for publication. Private server/client activation below remains separate. Drive archives were not updated.

# Heavy Bolt visual candidate - 2026-11-06

On `fix/weapon-retail-objectives`, a stowed Heavy Bolt uses its original world-space projectile trail after switching weapons. The correction covers the local predicted projectile (which has local authority) and its replicated counterpart, only for the original Heavy Bolt class fired by this exact remote local player. Other weapons and players are excluded. Projectile physics, ammo, damage and per-weapon timing remain native. Visual errors are isolated from input-release handling.

Validation: all 120 client tests and paired source checks pass. The isolated original-game `bolt-r2` qualification (external `verification/katabatic-bolt-20261106`) selected Heavy's alternate primary through the native inventory/loadout request, confirmed the Heavy Bolt grant, fired, switched weapons while the bolt was airborne, and read both projectile copies on the original world-space trail for 20 consecutive samples. Original initial speed remained 11500 cm/s. The actual visible predicted copy and hidden replicated copy were distinguished. All three original outer Jobs ended with zero owned processes. This was a rendered native process, but the whiteout itself was not visually inspected: both available app-control entrypoints failed to initialize with `failed to write kernel assets: The system cannot find the path specified. (os error 3)`.

The paired Katabatic two-client run separately passed both teams' flag returns and one-point captures/resets and all four authored turret initializations. Private activation completed with a saved local backup: only `lua/client.lua` and its package inventory were replaced in the package used by the desktop Starter shortcut. Its bytes match the native-qualified source, all 22 map fingerprints are unchanged, and other inventory rows are preserved. The paired laptop host update is active after an empty-lobby restart through its existing desktop task; pinned TLS confirms readiness, all 22 maps and spectator support, with active capacity 10. External readback evidence is `verification/katabatic-bolt-20261106/deployment/VERIFICATION.json`. Reopen Starter before starting a fresh test. The r7 complete client now publishes the same runtime as a playtest with visible whiteout confirmation still pending. Drive archives remain unchanged; native cross-PC gameplay was not requalified during activation. The diagnostic inventory reader, Blueprint inspection tool and native firing fixture are development-only; original assets, decoded data, executable files and native logs remain outside Git.

# Complete client release r6

The [2026-11-05 r6 complete playtest release](https://github.com/T24085/T3FrontEndClient/releases/tag/windows-2026.11.05-r6) is published. Its 1,445,721,840-byte ZIP was rebuilt from the pinned, fully inventoried r5 archive plus canonical frontend modules and first-person spectator runtime from commit `577b697d4db1128a0061a1d77e29ae338bcce99f`. All 5,522 declared files passed streamed SHA256 verification, all 22 map fingerprints matched a fresh read of the current server, and all six remote asset digests matched locally. The public download returned HTTP 200 with the expected size, ZIP signature and checksum.

Cooked maps, shared map-fingerprint Lua, original-game inventory and Python/Tk/native runtime binaries remain frozen. All 115 source tests and the exact extracted package's Python/Tk/control smoke checks passed. An extra bounded headless spawn check did not establish ready-player evidence and was stopped at the user's request, with owned process cleanup confirmed; it is not represented as a passing spawn qualification. Existing player spawning is confirmed by the user. Off-site multiplayer, loadout and distinct-player spectator confirmation remain separate. The main README now points to r6. No server update/restart was performed for publication.

# Lobby selection and membership recovery

Controls follow-up 2026-11-05: Automatic lobby/live-match polls now run as background work without disabling action buttons. A click during a background read is queued once and runs after that read; foreground operations still disable duplicate actions. The installed r3 update takes effect when Starter is reopened. The user's existing native game was observed running with `REMOTE_PAWN_READY` and has not been stopped.

Preparation follow-up: The reported wait completed in 210.76 seconds, including about 2 GB of cache verification. A warm file-only preparation still took 72.34 seconds. Profiling found serialized link creation dominated staging. Four bounded file workers now stage independent immutable files, with locked cache accounting/output; the same input/output identity, digest, private runtime and one-use descriptor checks remain. The measured warm preparation improved to 50.71 seconds, with staging falling from 53.83 to 34.89 seconds and zero bulk bytes rehashed. This has not restored 6-10-second cold-launch preparation on the two USB staging/package drives. A rejected native-copy trial was reverted. File-count progress is now displayed while Join waits. All 111 client tests pass, including worker overlap/failure cleanup, exclusive private copying, and progress parsing; no additional native game was launched for these probes.

Follow-up 2026-11-05: A lost map POST response could still clear the pending choice even when the server applied it. The r2 client distinguishes connection failures from server rejections, keeps the selected map visible, and reads fresh server state before retrying an idempotent map update. Three failed connection attempts stop automatic retries while Start remains disabled; choosing again retries. Server rejections retain their ordinary behavior. All 103 client tests pass, including replies lost before and after application, bounded outages, and denied selections. The installed client has the r2 modules with a backup; reopening Starter loads them. This works with the already-active r1 server and does not require a server restart.

2026-11-05: Map choices are queued while refreshes run; the latest choice stays visible until the server confirms it, and Start waits for confirmation. Joining checks the displayed map against the returned match before preparing or launching a game. Startup can resume the same verified device's lobby, Create recovers an existing membership, and closing/leaving releases membership in active and finished rooms. Recovery requires the paired backend update; the client remains compatible with older servers.

Validation: 98 discovered tests pass under Python 3.13.5 with the declared development dependencies, including delayed-reply Tk controls, transport recovery, map checks, and updater rollback. Paired source checks pass. The local installed client received only the three recovery modules with a saved backup and refreshed inventory; map inventories were preserved. Small client/server updater ZIPs were prepared outside Git. The paired laptop server update is now active: live pinned TLS from the installed client confirms recovery enabled, all 22 maps, and no stale membership for the testing device. No native multiplayer game was launched for this change. The separate armor/weapon issue below remains unresolved.

# Current source changes

2026-11-05: Spectating is limited to first person while third person remains incomplete. The viewer starts in first person, restores it after native perspective toggles, and keeps F5/F6 player switching and F7 first-person reset. F8 third-person selection is removed. Launcher help and generated playtest instructions match this policy. Dynamic and desktop builders now include the canonical spectator runtime when the verified input declares spectator support.

Validation: all 95 discovered unit tests pass under Python 3.13.5, including seven Lua 5.4/candidate-building regression checks. The paired source check parses 57 Python sources and verifies ten shared contracts. Local Tk tests require TCL_LIBRARY and TK_LIBRARY to point at that interpreter's installed tcl8.6 and tk8.6 directories. This is source and synthetic candidate validation; a full player package, native in-game qualification, installed-client update and deployment have not been performed for this change. Existing session-recovery work is separate.

# Baseline status

Imported on 2026-11-04 from the existing community starter project and verified source inventories. The active source catalog contains 22 maps. This import does not rebuild packages, alter desktop shortcuts, restart services, or change a live game.

Release `windows-2026.11.04-r5` uses the complete Windows r5 player package. Every one of its 5,521 declared files passed streamed SHA-256 verification, and its 22 map fingerprints match a fresh read-only verification of the current server. Source catalog helpers now retain all 22 map choices, including the eight native map identities. This verifies distribution integrity and content compatibility, not a repair of the gameplay issues below.

An admitted player could remain on native staging team 3 while another player spawned. The backend correction is on `fix/multiplayer-join-loadouts` and was installed and activated on the laptop server on 2026-11-04. Readback verified its exact runtime hash, unchanged map fingerprints, all 22 maps and the configured capacity of 10 simultaneous matches. This does not claim ten populated matches were stress-tested.

Fresh isolated native qualifications now observe the staging-team transition, both medium (529) and heavy (531) players spawning, the original match clock advancing, and all five original owned Jobs empty after cleanup. A separate rendered loopback run showed weapon icons and names for light, medium and heavy armor; selecting the original Thumper option updated the menu and the menu returned to gameplay. The earlier 85-second timeout is superseded. These are bounded loopback results, not off-site multiplayer or full-match qualification. The double-shot issue is recorded as fixed based on the user's confirmation. The existing weapon-input fix is already present in the imported frontend.

The direct-port-forwarding friend handoff is experimental and separate. It has transport/source checks, not complete off-site native qualification.

Maps: Damnation, HighOctane, Scarabrae, Stonehenge, Snowblind, Rollercoaster, SnowblindBlizzard, HighOctane2026, Damnation2026, Scarabrae2026, Stonehenge2026, Snowblind2026, SnowblindBlizzard2026, Rollercoaster2026, Torment, DangerousCrossing, Drydock, Katabatic, Wavemist, Hollow, Raindance, Moonrise.

# Team radar with backup sensors

On layouts that declare multiple sensors per team, a connected client
reconciles the native team radar flag from the full set of replicated
sensors. Radar stays online while any sensor still has power and is
operational. The client also waits for all authored sensors before asking
the native minimap binder to populate the sensor layer. The paired backend
change is tracked in Tribes3-Modded/T3BackEndServer issue #38.
