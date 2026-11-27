# Recovery and CTF bot training

The local trainer now has low-energy recovery and mirrored Capper vs. Chaser
drills. Adaptive CTF movement can keep the native combat AI active during
visible engagements. Defenders share recent sightings and split pursuit and
cutoff assignments. Season offense tracks capture windows following nearby
equipment clears. New campaigns can consume same-map, qualified movement and
pursuit profiles, as well as imported human movement references.

High Octane native qualification saved two mirrored duels with real flag
pickups and one confirmed hit from an airborne chaser on each side. Both
legs ended at the time limit. A separate four-bot recovery wave verified a
34.2 km/h sideways shove at roughly 34 energy, followed by 1.4–4.3 second
recoveries and zero observed jogging. The initial survey had hit overhead
collision above a spawn. The revised survey checks the height band at the
surface where the pawn is standing. A native 2v2 benchmark completed both
legs from matching reserved starts, with a 0–0 score in each leg. The
owned hosts exited with zero remaining processes. The dashboard is live
with both drills and reports jogging during open travel. The first native
7v7 saved a flag pickup, four cutoff assignments and 13 confirmed damage
events from airborne launches. The match ended 0–0. Open-travel jogging
reached 20.5% for one bot. The updated movement handoff keeps ski input
available when native navigation resumes outdoors and jets after sustained
low-speed travel. In the repeat 7v7, combined open-travel jogging fell from
10.23% to 0.03% and the highest individual share fell from 20.47% to 0.38%.
The repeat ended 0–1 with two pickups and eight confirmed damage events
from airborne launches. Both matches recorded base equipment snapshots,
and neither recorded an equipment destruction. Capture-window credit was
verified with controlled evidence. The mixed-player smoke check reached a
native Red player with a 7-blue and 6-red bot roster, wrote a movement
trace and cleaned up both game processes. No active human movement
recordings have been imported.

# Hill movement drills

Flight Fundamentals offers Downhill momentum and Uphill jets alongside
Straight flight. Each hill lane checks native terrain collision for a
continuous 80-metre slope. The uphill drill uses the same slope in reverse
and waits for the bot to settle at the bottom with full energy.

Downhill profiles compare ski timing against running using completion,
entry and exit speed, and momentum retention. Uphill profiles compare jet
timing against skiing alone using completion, elevation gain and forward
distance under jet power. Paired waves reuse the identified courses.

The dashboard and launch API are live. The course selector found spaced
endpoints for all 24 recorded High Octane starts in the authored terrain
heightfield. The installed host templates compiled and both browser
fixtures verified launch, scoring and replay loading. In-game verification
of the hill courses is outstanding. The operator's 50-wave straight-flight
run continued on its original training worker through publication.

# Flight fundamentals

The local dashboard has a Movement mode for flight fundamentals. The default
is ten Light bots per wave, three waves, and 30 seconds per wave. The drill
uses native spawn headings and a 160-metre goal, with flag pickups and bot
combat disabled. It records forward distance, pace and time under 15 km/h,
airtime, jet use, and a replay for each bot.

Flight trials compare running, skiing, and three jet timing profiles. With
three or more waves and sufficient jet flight on both sides, the final two
waves compare the selected profile with the running baseline across the
same starts. Both sides must gain speed and record actual forward flight.
The dashboard can start a drill while idle without advancing a waiting
season queue. When the trainer is busy, the drill uses the existing queue.

The dashboard and launch API are live. The first release passed training
and client tests, native host template compilation, an isolated Lua input
and checkpoint check, and browser tests with fixture results. The native
High Octane check saved all 30 attempts across three waves in one host.
Steady jets passed the paired check at five starts per side. Median speed
rose from 11.9 km/h to 65.1 km/h on Blue and 73.8 km/h on Red. The bots
covered medians of 132.6 m and 113.0 m of forward distance in the air.
All 30 traces are available under Flight fundamentals · High Octane
verification. The native host released every owned process on exit.

# Mobile training dashboard

The dashboard uses the selected map's terrain in its header and adapts the
training panels, history, and replay controls to both light and dark themes.
The Training view shows the active or latest run, with direct replay links for
its three most recent team matches. Resume, pause, and queue actions still use
the existing training API.

Training, Results and History are separate views. History searches by run
name, map or status and shows six runs per page. The training queue opens on
demand. Results put replay controls ahead of match details. Playback and
scrubbing hold the selected match and run as live results arrive. Touch can
scroll over the map until Pan map is enabled.

The mobile build was published while the active season worker continued
running. Browser checks exercised touch playback on saved traces, including
a new result arriving mid-replay, along with history search and paging.

# Local bot training calibration

The local dashboard presents eight training modes and all 24 current maps.
Mirrored aim calibration compares each side's confirmed projectile damage
rate against its own native-aim baseline. Results record airborne state at
launch for the shooter and at impact for the target. The five-capture CTF
rules and native starting conditions are pinned for compatible calibration
and season benchmark games.

The native recorder verifies both sides' aim settings before accepting a
game. Warm reuse requires an exact verified reset. Completed games are
saved if a reset is rejected or Windows runs low on available commit.
In bot-only waves, the reset may retire new actors of the exact native
death-drop class if they are the only world difference. It excludes
original map pickups and other worlds and verifies the full snapshot
again. The first native cleanup check preserved its saved game and fell
back to a fresh host. A 7v7 check verified two waves in one host with
wall times of 216 and 123 seconds. In a separate controlled High Octane
test, the runtime removed a seeded actor of the native death-drop class
and completed the second wave in the same host. Cleanup left zero owned
processes. The player guard covers remote connections and controllers
with a pawn while allowing an empty headless local controller.
Results with partial combat coverage are retained for review and excluded
from selection. Only a profile with enough complete mirrored pairs and a
positive result from both sides can enter a matching held-out benchmark.

The completed Stonehenge 7v7 calibration saved 16 games, 1,663 tracked
launches, and 223 confirmed damage events. Each profile has four complete
pairs. The 10% profile changed Blue and Red by +15.1 and -2.7 percentage
points. The 20% profile changed them by +9.6 and +0.6 percentage points.
The 20% paired confidence interval spans -2.2 to +12.4 percentage points.
Neither profile qualified. Native aim remains selected. The dashboard
serves all 16 results, combat events, and bot replays from the verified run.

The combat API labels the four projectile classes observed in calibration
with their weapon families. It retains the original projectile class and
identifies the source of the label. Unmapped classes keep their native names.
The labels passed desktop and narrow viewport checks with recorded events
and are live on the training dashboard.

Two 240-second High Octane 7v7 season games each recorded a flag pickup,
carrier chase and Red capture. The games saved eight offensive and twelve
defensive samples, 703 projectile launches, and 59 confirmed damage events.
Neither game recorded base equipment going down. The first game's unverified
warm reset preserved its result and retried on a fresh host. Both replays
are listed under High Octane 7v7 season qualification. The reset now checks
the retired actor's native name and address together. A regression test
verifies that a new pawn can reuse a retired address, and that the retired
identity still fails validation. A separate native High Octane 7v7 check
completed two 105-second games in one host. The cold wave took 213.78 wall
seconds and the warm wave took 123.10. All 14 spawn receipts matched and all
28 traces were retained. The native check did not encounter address reuse.
The host released every owned process on exit.

The live saved-run comparison shows captures per pickup, returns per
drop, and carrier downs per enemy pickup for Blue and Red. Archived bot
totals can supply capture rates when they agree with the scoreboard.
The live High Octane archive reports 8 captures from 74 Blue pickups and
26 from 149 Red pickups across 150 games. It has no flag-return ledger.

A held-out benchmark using a qualified aim profile shows its own damaging
shots per tracked launch for each side against the same-side baseline, with
excluded-pair counts. It retains the capture comparison. The held-out
dashboard view passed a browser check with fixture data. The live comparison
passed browser checks using two existing game records. All 60 training
tests, 115 client tests, and source checks passed.

# Training waves across modes

2026-11-19. Every dashboard mode accepts one to five waves per launch, with
five as the default for new requests. Existing request settings are retained.
Team modes checkpoint each result and update eligible capper, defensive and
offensive feedback before selecting the next wave. Native bot rosters are
recreated in the loaded world, with held spawn preparation, verified positions,
health, energy, velocity, flags, scores, clocks and native actor retirement.
Unverified resets and changed map state preserve saved matches and use fresh
hosts. Trace paths remain unique and compatible with map replay.

Two 30-second native Stonehenge 7v7 matches completed in one owned process.
The first wave took 186.98 wall seconds including startup; the warm wave took
51.85. All 14 starting positions matched exactly, with full native health,
100 energy and zero velocity. All 28 trace files were retained. The cleanup
receipt recorded zero active processes at parent exit. This short check
qualifies wave reset and recording, rather than combat learning quality or
all maps and modes. Eligible learning remains pressure-gated.

All 46 training tests, 115 client tests and source checks pass. The verified
build is live on the existing Tailscale dashboard. Browser checks confirmed
the wave selector in all seven modes and resumed the owner's Stonehenge run
at five of ten saved matches, with five waves per launch. Live HTML identity,
owner access and the worker command line were verified. Operator evidence
and source backups remain outside Git.

# Training route replay and map overviews

2026-11-19. The local dashboard supports synchronized route playback for a
saved match and playback of an individual bot trace. Controls include pause,
restart, scrubbing, playback rate, bot selection, map extent, zoom and pan.
Flag and death events seek to their recorded timestamps. Interpolation
preserves event ownership changes and skips death and teleport gaps.

Seven main 2026 maps have source terrain overviews with flag stands and spawn
markers. The imagery comes from checked source heightfields, transformed
into the Unreal world coordinate system. These overviews show elevation.
Other maps retain the coordinate plot when terrain imagery is unavailable.
Assets and operator metadata are stored outside Git.

Four playback math tests and 35 Python training tests pass. Browser checks
covered 24 simultaneous routes, play and pause at 4x, seeking, bot selection,
zoom, pan and map extent. A recorded 7v7 High Octane match confirmed the flag
pickup and capture event jumps and the corresponding carrying state.

All 115 client tests and the source checks pass. The client tests used an
E-drive temporary directory because C-drive free space was below the
staging reserve. The frozen replay build is published on the existing
Tailscale dashboard at port 8444, with its HTML and map endpoints verified.

# Local training wave reuse

2026-11-19. Route Screening supports one to five checkpointed waves per native
host launch. Every warm lane requires a reset receipt. Failed resets retain
completed waves and continue with fresh hosts. New dashboard requests default
to 24 cappers and five waves per launch. Existing saved requests retain their
settings. The dashboard exposes recorded contacts per hour and reset counts.

All 32 training tests, 115 client tests and source checks pass. A local native
Damnation check completed two waves with two cappers, followed by one fresh
control wave. All six starts had identical lane positions, zero horizontal
velocity and 100 energy. Both warm reset receipts passed. The warm wave took
35.71 seconds for a 30-second trial, and the fresh control took 194.12 seconds.
All owned native processes exited. This small check does not establish the
distribution of outcomes or throughput for 24-bot campaigns.

The local Tailscale dashboard serves the verified build. Its results endpoint
and owner access were verified, and its analytics were inspected in the browser.
Authenticated form interactions were covered by backend tests. The browser
could render the local results view. The user's Rollercoaster 7v7 campaign
remains paused at four of fifty saved matches.

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

The real-player join failure was reproduced: one admitted player remained on staging team 3 while the other spawned. The local correction is preserved on the backend branch `fix/multiplayer-join-loadouts`; it was not deployed at import time. A corrected isolated native run spawned one medium and one heavy client, but its overall qualification timed out before the match-start check completed. Missing weapon boxes in the armor/loadout menu remain unresolved. Do not describe either issue as fully fixed or deployed.

The direct-port-forwarding friend handoff is experimental and separate. It has transport/source checks, not complete off-site native qualification.

Maps: Damnation, HighOctane, Scarabrae, Stonehenge, Snowblind, Rollercoaster, SnowblindBlizzard, HighOctane2026, Damnation2026, Scarabrae2026, Stonehenge2026, Snowblind2026, SnowblindBlizzard2026, Rollercoaster2026, Torment, DangerousCrossing, Drydock, Katabatic, Wavemist, Hollow, Raindance, Moonrise.

## 2026-11-27 · M3 · Mirrored bot training checkpoint

The trainer restores defense and offense tactic pairs as tuples before scoring
the mirrored leg. The regression saves the first leg, reloads the checkpoint,
and verifies that both sets of tactics remain usable as scoring keys and that
the second result is saved. Frontend issue #109 tracks verification on the
private laptop trainer.

## 2026-11-27 · M3 · Sustained bot flight

New straight-flight drills rank jet profiles using fast airborne advance,
gliding and momentum through landing. The dashboard exposes these native
measurements, and an offline analyzer reads saved capper traces and public
flight references. Frontend issue #111 tracks native and laptop verification.
Rescoring 600 saved High Octane traces switched the preferred profile from
steady jets to long jets. The latter still needs a paired native evaluation.

The campaign dashboard plots fast flight, jet use and unpowered glide by
match. Historical traces can be summarized in a separate evidence file and
displayed alongside new matches with the same definitions.

## 2026-11-27 · M7 · 3D route replay

Training replays can follow one bot from a chase camera using the recorded
world coordinates and playback clock. A local High Octane preview uses the
verified source heightfield. Maps with a legacy overview use a flat reference
plane. Frontend issue #115 tracks private dashboard rollout.
