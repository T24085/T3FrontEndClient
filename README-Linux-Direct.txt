TRIBES 3 DIRECT STARTER - LINUX / STEAM PROTON

Requires x86-64 Linux, Python 3, Steam, and your installed copy of TRIBES 3: Rivals.
The package contains the public GameServer01 enrollment and signed Starter.
Steam supplies the original game and Proton.

1. Extract the complete archive to a permanent folder in your home directory,
   outside the original game. Keep the old Starter folder until the new one
   has launched successfully.
2. From the extracted folder, run:
      sh "Start Community Starter.sh" --setup
3. In Steam, open TRIBES 3 > Properties > Compatibility and enable Proton.
   Replace the launch option under General with the entire line from step 2.
4. Click Play in Steam, then join Public CTF in the Starter.

Keep using Play in Steam. The Starter checks GameServer01's signed Direct feed
and syncs map updates from the host. Private lobbies require separate host
access. Remove the Steam launch option to go back to the original game.

Linux launcher and package checks do not establish gameplay compatibility.
Steam/Proton multiplayer and Steam Deck Gaming Mode need player testing.
Logs are under the following directory (or the equivalent XDG_DATA_HOME path):
    ~/.local/share/Tribes3CommunityStarter/linux-launches/
A specific run contains linux-launcher.log and bridge.log. Share the error
details and Proton version when reporting a problem.
