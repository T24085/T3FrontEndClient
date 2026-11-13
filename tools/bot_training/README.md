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

This first trainer learns movement settings for the one route task. The next
step is to learn a state-dependent controller from demonstrations, then
fine-tune it on repeatable attempts that also vary speed and energy. A
capture-capable controller can then be evaluated with defenders and under
public-server bot load.
