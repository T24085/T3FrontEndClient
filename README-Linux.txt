TRIBES 3 COMMUNITY STARTER - LINUX / PROTON R12

This is an x86_64 Linux compatibility candidate. It runs the existing Windows
client through Steam Proton. The Linux launcher is tested separately from the
game: see linux-support.json for the exact verification status of this archive.
It does not include a server, Steam, Proton, or the original game.

ONE-TIME SETUP

1. Install TRIBES 3: Rivals in Steam using your own account. Connect Tailscale
   to the playtest network. For first-time access, open the shared server setup
   page in a browser and enter the playtest code from your organizer.
2. Extract this entire .tar.gz into a permanent folder under your home directory.
   Use an ordinary local Linux filesystem with enough space for an isolated
   game copy. Do not extract into the original game's installation directory.
3. In a terminal in the extracted folder, run:
      sh "Start Community Starter.sh" --setup
   This prints the exact launch-option line for your installation path.
4. Steam > TRIBES 3 > Properties > Compatibility: enable a Steam Proton version.
   Under General > Launch Options, paste the entire line printed in step 3.
5. Click Play for TRIBES 3 in Steam. Community Starter opens through Proton.
   Create/join a lobby and click Join game after the match becomes ready.

After setup, use Play in Steam each time. Starter checks the signed r12 update
channel before opening the lobby. Compatible cooked map updates sync from the
connected server. The archive includes all 22 map choices from the live host.

Keep the extracted folder in the same
location; if you move it, repeat steps 3-4. Remove the launch option to return to
the original Steam launch. Setup does not edit Steam configuration for you.

HOW IT WORKS

Steam owns the selected Proton version, prefix, runtime/container and signed-in
account. Our wrapper preserves that command and replaces its game target with
Community Starter. The game's original Steam SDK reads your player name.
The dwmapi override enables the included UE4SS loader. Windows process ownership
must pass a startup test before a game can be opened; unsupported implementations
fail with an error instead of silently disabling supervision.

TLS stays enabled. Each launch imports a snapshot of the Linux system CA bundle
and checks its digest before opening the HTTPS lobby; hostname checking remains
required. No certificates are installed into system stores and no verification
is disabled. Original game executable and assets are verified, staged, and kept
separate from the community runtime, using the same pipeline as Windows.

Player settings live inside the game's Steam Proton prefix. Staging and launch
logs use ${XDG_DATA_HOME:-$HOME/.local/share}/Tribes3CommunityStarter.
The first original-game verification can take several minutes. Existing file
preparation/reuse is retained; game joining waits for actual startup evidence.

TROUBLESHOOTING / TEST REPORTS

- Linux Steam must already run with your own signed-in account. An ARM Jetson
  cannot use this x86_64 package. No native ARM or native Linux game port is included.
- If setup says Python is missing, install Python 3 with your distribution's
  package manager. The Windows Python/Tk needed by the UI is included.
- A stale or wrong Proton install can fail the ownership preflight. Change the
  game's selected Proton version and retry. Do not disable that check.
- If lobby contact fails, check Tailscale connectivity first, then clock and CA
  certificates. The server uses the same private Tailscale endpoint as Windows.
- Logs: linux-launches/<launch-id>/linux-launcher.log, bridge.log,
  bridge-ready.json and job-check/execution.json under the data directory above.
  If the game starts, also include the matching session's events.txt and game.log.
  Do not upload complete Steam profiles, account files, certificates or credentials.
- For the first gameplay test, report your distro, GPU, Proton version, whether
  the Steam name/lobby works, and whether spawning, movement, jetting, abilities,
  flag pickup/capture, respawn and quitting work. A lobby screen alone does not
  establish that the UE4SS gameplay runtime works under that Proton version.

Native Steam on x86_64 Linux is the initial target. Flatpak Steam and Steam Deck Gaming Mode
require their own end-to-end validation; sandbox access to the extracted folder
and Python can differ. The server is unchanged and remains on the host PC.
