# Local bot movement practice

Run **Record High Octane Practice.bat** in `E:\T3-Bot-Training`. Wait for the
practice window to open and for the launcher to say it is recording. Run several
routes toward the enemy flag and include recoveries after missed landings.
Close the game normally when done. Restart the launcher for a separate recording.

Each run writes `movement.csv` under `E:\T3-Bot-Training\Sessions`. It samples
the local pawn on a 50 ms game-thread timer and records actual game timestamps,
position and velocity in Unreal centimetres, view angles, energy, ground
contact, world-space movement input, ski request, and jet ability input state.
The segment number changes when the pawn changes. The first version uses the
blue side. A short gap or final partial batch may occur during a respawn or exit.

The launcher uses an existing verified game cache, separate local profiles and
the Windows Job supervisor. It starts a loopback-only host with no bots so
you can repeat routes. It records the local pawn during this session only.

## Automated movement trials

### Recovery, pursuit, and full CTF

In **Flight fundamentals → Low-energy recovery**, each bot spends jet energy
in the native game and receives a sideways shove at a surveyed slope. The
trainer verifies starting energy and lateral speed before it times the bot.
Recovery requires sustained forward speed, controlled lateral drift, and
skiing or flight. New flight drills also score grounded jogging. The final
two waves use matched starts to compare the candidate with the baseline.

**Capper vs. Chaser** swaps sides after each game. A real flag pickup starts
the clock. Each replay reports the outcome, shots fired while airborne, and
confirmed carrier damage. Three pursuit lead times rotate across pairs. A
profile needs usable combat evidence from at least two matches per side
before a later run can use it. Twelve games give each profile two pairs.

New team runs share visible sightings within a team. A sighting expires
after 3.5 seconds. One defender pursues the carrier and a second takes the
cutoff, while the heavy keeps its flag coverage assignment. Ski and jet
travel can continue during visible engagements while the native combat AI
aims and fires. New runs can use qualified flight or pursuit profiles from
the same map revision. Season offense scores capture windows following
observed equipment clears near a support bot and checks that the same
capper finished the capture.

**Role scrimmage → Compare with baseline** uses reserved native starts and
rotates compatible saved opponents when available. Both legs of a pair need
matching native spawn receipts and the same frozen opponent. The dashboard
shows matched, pending and excluded pairs.

`play_trained_bots.py practice.json --map HighOctane2026 --side red` starts
an isolated human playtest with the local player on Red. Use `--side blue`
for the other side. Add `--record` to capture your movement in that match.
The existing Play Trained Bots launcher defaults to Blue and accepts these
arguments.

For movement references, record local play using the practice recorder.
Import the completed `movement.csv` files with
`python tools/bot_training/human_reference.py practice.json HighOctane2026 first.csv second.csv third.csv`.
Recordings must contain sustained movement and a jet takeoff. After three
unique recordings on the current map revision, new matches can use the
reference jet energy reserve. The trainer stores aggregate movement
measurements and a deduplication hash in the private training directory.

Run **Train High Octane Bot.bat** on the same PC. It launches one headless,
local game host and one blue bot. The bot steers toward the opposing flag,
then toward its own stand after pickup. The trainer uses a bandit algorithm
to choose ski use, jet timing and steering offsets from trial rewards. The
baseline uses straight steering with skiing and jets off.

Each attempt starts at a selected blue spawn from rest with full or nearly
full jet energy. A pickup is credited when the native flag owner changes
to the bot. A capture requires a pickup and a native team score increase.
Training ranks attempts by capture, pickup and approach distance. The
final comparison uses a held-out spawn and three offsets per policy. It
ranks the policies by captures, successful capture time, then pickups and
grab time. The report separates spawn-to-grab, grab-to-cap, and total cap
time. It also shows the average and peak horizontal speed in km/h, with
separate averages before and after the first grab. The average includes
acceleration, braking, and time stopped. See `trials.jsonl` and
`evaluation.json` in the run folder.

For a repeatable speed check, run the training launcher with
`--qualify --attempts 4 --seconds 76`. Add `--fast-approach` to run later
braking. To compare both settings, use `--qualify --compare-approach
--attempts 2 --seconds 76`, then repeat with `--start-index 2` for the next
two starts. A match ends after five captures. Each qualification writes
`qualification.json`.
The first attempt uses the known pickup start. The other three use a held-out
spawn with different offsets. The test uses one blue bot without defenders.

Use `--qualify --compare-routes --attempts 1 --seconds 76 --start-index 1`
to compare the direct route with mirrored side and back approaches from
one spawn. The flags define the route coordinates. The side approaches
pass a lateral waypoint, and the back approaches add a waypoint behind
the stand. These waypoints are candidates for trial runs.

The report keeps mean and median times alongside the individual fastest
grab and cap. Each trial has a `trace-N.csv` with positions, velocity,
skiing, jetting, and energy. The grab row records speed and the component
of velocity toward home. A negative homeward speed means the bot must
turn or brake before returning.

## 100-attempt batch

Run `Train 100 High Octane Attempts.bat` to start or resume the local
100-attempt campaign. The trainer opens successive matches and saves
`Campaign-100-20261113/progress.json` after every completed trial. The
first 90 trials tune preset routes, ski, jet timing, braking and steering.
The final ten compare the selected settings with the current direct
baseline on five identical, held-out starts. Keep Steam signed in.

Run `Train 1000 High Octane Attempts.bat` after the 100-attempt campaign
finishes. The larger run uses the winner of the matched comparison as
its starting policy and tries additional braking distances around it.
The campaign length and policy configuration are pinned when a folder
is first created.

This first trainer learns movement settings for the one route task. The next
step is to learn a state-dependent controller from demonstrations, then
fine-tune it on repeatable attempts that also vary speed and energy. A
capture-capable controller can then be evaluated with defenders and under
public-server bot load.

## 25-attempt defended pilot

Run `Train 25 Defended High Octane Attempts.bat` from the local training
folder, or run `defense_batch.py <practice.json> <campaign folder> --attempts 25`
with Python and the same local configuration. The loopback-only host uses one blue
Pathfinder against a red Heavy on Flag and a red Light Defense bot.
The defenders use stock bot combat with scripted positioning and pursuit.
The capper uses upper-confidence-bound selection among preset direct,
side, and back routes and their movement settings. The first 15 attempts
select settings. The final ten compare the selected policy and baseline
on five paired starts excluded from training.

In addition to the solo movement and flag metrics, the checkpoint records
capper deaths and damage, time the Heavy spends near the flag, time the
Light spends near the carrier, each defender's time alive, and red captures. Check the host's
`BOT_ROLE_READY` and `MATCH_RULES_BOTS_READY` events for the native armor
and roster used for each run.

## Follow-up with grounded defenders

Run `Train Next 25 Defended High Octane Attempts.bat` to queue the follow-up
behind the first defended batch. The first batch keeps its own checkpoint.
The follow-up starts both defenders from floor-checked anchors near the red
stand and waits for both to settle before timing the capper. The Heavy
returns to its anchor outside combat. Light Defense pursues an approaching
capper or flag carrier. Both use their stock combat behavior near the capper.

The follow-up checkpoint adds median time alive, Heavy flag-area time,
Light Defense carrier proximity, and capper damage. It reports those same
measurements separately for the two held-out policies.

Run `Train 50 Defended High Octane Attempts.bat` after the grounded batch
completes. It uses the previous matched winner as the baseline, spends the
first 40 attempts refining approach distance, steering, and jet timing,
then compares the selected settings against that baseline on five new
paired starts. The 50-attempt checkpoint stays separate from both pilots.

Run `Train 100 High Octane Defense Attempts.bat` to train the defenders
against the winner of the 50-attempt capper comparison. The capper settings
stay fixed. The first 90 attempts select among eight combinations of chase
range, aim lead for pursuit, and when each defender hands off to stock combat.
The final ten pair the selected defense and the original defense on five
starts omitted from training. Reward favors denying a capture or grab,
then accounts for damage and delay. A capture denial includes a timeout.

Run `Run 144 High Octane Matchups.bat` to compare eight capper settings with
four Juggernaut and Light Defense profiles. Each combination runs once on
each of three training starts. Twelve held-out starts then compare all four
pairings of baseline and selected capper and defense. Results record captures,
denials, damage, deaths, speed, and the trace from each attempt.

Run `Run High Octane Flag Pass Pilot.bat` to compare the braking route with
four ski-through approaches using 45 m and 70 m runups behind the flag.
Each route runs on the same four starts against both defense profiles.
The fly-through segment preserves forward speed while steering toward the
flag line. If the bot overshoots, it can recover with the original controller.
The report separates recovery grabs from first-pass grabs and records
horizontal speed, velocity toward home, and capture conversion. A pass
that misses also records the closest distance to the flag and speed there.

`Run High Octane Flag Pass Expansion.bat` queues 108 attempts behind
the 40-trial pilot. It finishes the pilot from its checkpoint if the
original pilot process stops. It repeats the original routes, including
the braking control, and adds two height-aware jet timing variants to
each of the two best pilot pass lines. All nine routes run against the
same two defense profiles on six new starts. The results count pickups
at 200 and 330 km/h while moving toward home, and captures after 200 km/h
pickups. The current pilot and the expansion use separate checkpoints.

In the dashboard's 7v7 Role Scrimmage and 4v3 Offense vs. Defense modes,
each defensive role tries positioning and pursuit tactics. The next match
uses the saved results to choose tactics. Rewards combine flag pickups and
captures allowed with positioning while an opponent threatens the flag.
Heavy on Flag is scored on stand coverage, Light Defense on pursuit, and
Medium Defense on supporting the interception. A side with under eight
sampled frames of flag pressure adds no defense reward. Training reports
record each chosen tactic and the evidence that contributed to its reward.

Medium and Heavy Offense can try early, timed, and late pushes relative to
their cappers' approach. The trainer rewards coordinated pressure near the
stand, nearby guards leaving the stand, and team flag outcomes. Guard
departures are observed events and may have multiple causes. Each match
records the chosen profiles and the stage and push commands issued.

Same-map team matches contribute to the roles that participated. Team CTF
and Cappers vs. Defense also vary the tactics of the roles they field.
High Octane's grounded-defense and Juggernaut drills seed Heavy and Light
Defense. Older team traces can seed baseline tactics for their named roles.
Solo and Route Screening contribute capper evidence. They need a defended
stand and supporting offense to produce evidence about an offensive push.

Capper route selection deducts points for slow contact, failing to build
speed below 100 km/h, and losing more than 5 km/h from the peak in the final
30 meters. A fast pass can maintain its speed. Older results contribute
their recorded fields. Route Screening reserves roughly one lane in five
for new runs with different run-up distances, steering and jet pulses.
Every fourth team match reserves one guided capper for those experiments.

Route Screening can run one to five waves per game launch. New dashboard runs
default to 24 cappers, ten waves, and five waves per launch. Each completed
wave is checkpointed before the next route selection, so new evidence feeds
the next wave immediately. Pause waits for that wave to save, and Stop now
discards the unfinished wave. Resume starts a fresh host at the next unsaved
wave. Existing requests retain their recorded launch settings.

Warm waves require native reset receipts for every lane. Checks cover pawn
identity, health, energy, movement input, active effects and abilities, flag
ownership, team scores, position, and live projectiles. A failed reset retires
the owned host and continues the remaining waves with fresh hosts. Each trace
keeps its own lane and wave number. The dashboard reports recorded contact
throughput, contacts at 100+ km/h per hour, and verified resets.

Match routes and individual trial views include recorded route playback.
Play, Pause, Restart, the time slider and playback speed control share one
timeline across the selected bots. Event buttons seek to the recorded flag
pickup, release, capture or death. Death and teleport gaps stay disconnected.
Fit routes and Full map set the view extent. Drag the map to pan and use the
zoom buttons for a closer view.

Terrain overviews are generated from the preserved source heightfields for
the seven main 2026 maps. Flag stands and spawn markers use the training
host's world coordinates. Other maps retain the coordinate view until an
overview is available. Generated PNGs and metadata live in the operator's
MapOverviews directory beside DashboardRuns. The build_map_overviews.py
command takes the practice configuration, original and expanded heightfield
directories, and the output directory.

All dashboard modes expose one to five waves per game launch. Team CTF,
role scrimmage, offense vs. defense, capper groups and exploration keep the
loaded world and recreate the native bot roster between waves. Each match
checkpoints its routes and eligible role feedback before selecting the next
wave's routes and tactics. Class composition changes start a fresh host.

Preparation holds and protects newly spawned bots until the roster is ready.
Additional spawn rows are spaced six meters forward from native player
starts, with native collision checks and grounded readiness. The first wave
records those grounded positions. Subsequent waves restore those exact
positions with zero velocity, full native health, fresh native loadouts and
settled energy. Protection ends before recording. Flags return home,
projectiles are removed, team scores and match clocks reset, and retired
controllers and player states must pass native destruction checks. Changed
base equipment, persistent deployables or capture-point ownership require
a fresh host. No warm wave counts without its native reset receipts.

Compare saved runs shows each side's captures per observed pickup, flag
returns per observed drop, and enemy carrier deaths per enemy pickup. The
table lists denominators and marks unavailable telemetry. Capture events
or saved per-bot totals must agree with the scoreboard for the game to
count towards that rate.
Runs show their map and rules build identities alongside the comparison.

Under Role scrimmage, Calibrate aiming tests the 10% and 20% redirect
profiles in mirrored pairs. A qualifying game needs complete projectile
recording, five tracked launches per side, and at least one native aim
decision redirected only for the candidate. Compare Blue to its own baseline
and Red to its own baseline using the share of shots with confirmed damage.
Start with eight pairs to test each profile in four pairs. Selection also
requires a gain on both sides and a positive lower 95% interval bound.

Calibration can reuse a verified clean wave and checks which aim setting the
native observer installed on both teams every game. Paired runs use the five
capture rules when those rules are installed. A season benchmark can use a
qualified profile from a calibration with the same map revision, rules,
roster, duration, and frozen candidate tactics. Benchmark games start fresh
and stay outside both training and calibration history. When a benchmark
uses a qualified aim profile, its held-out accuracy table shows confirmed
damaging shots out of tracked launches for each side under the candidate
and baseline. Both games must have complete combat evidence to enter it.

Solo and legacy defended campaigns retain their trial format and guarded
reuse checks. Combat, captures or inaccessible state can require a fresh
host. Pause checkpoints before another wave is requested. Stop discards the
unfinished wave; Resume starts a fresh host at the next unsaved match.
The team dashboard reports verified reuse and timed matches per hour,
including recorded startup, reset preparation and failed-reset time. Older
matches without wall-time evidence are excluded from that rate.
