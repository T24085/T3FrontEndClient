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

## Reinforcement learning follow-up

1. Fit a small movement policy from demonstrations. Hold out entire sessions.
2. Build a headless, single-bot test that can reset spawn pose, velocity, energy,
   route progress and previous input. Verify resets against native telemetry
   before batching. The current recorder does not implement the action and
   reset loop.
3. Start with a simple search over jet pulse and turn parameters as a baseline.
   Then fine-tune the movement policy using repeated rollouts. Reward progress
   through ordered route checkpoints and verified flag arrival. Penalize
   timeouts and going out of bounds.
4. Rank policies by completion rate on held-out starts, then median time among
   completions. Vary speed, angle, energy and landing conditions. Compare
   against the stock bot and the demonstration-only policy on the same starts.
5. Recheck the winning policy in native practice and measure server frame
   times with 24 bots before considering a public rollout.
