# Launch Phoenix Rising without keeping a terminal open

These steps are for the native Linux preview. For your first run, execute the
installer in a terminal so you can see setup and startup output.

```sh
sh "$HOME/Downloads/Install-Clan-Wars-Ubuntu-Native-Preview-7-r75.run"
```

Complete **Steam Setup** in Starter and keep the launch option it gives you in
Steam. The installer prints the folder it installed to.

## Run detached from a terminal

After the first launch works, run the installed launcher in its own session.
Use your actual installation folder if it differs from the example.

```sh
launcher="$HOME/Games/Clan Wars Ubuntu Preview 7 r75/Start Clan Wars Ubuntu.sh"
setsid -f /bin/sh "$launcher" </dev/null >/dev/null 2>&1
```

You can close the terminal once the launcher opens.

## Add an application menu shortcut

Create the applications directory and save the following as
`phoenix-rising.desktop` in that directory.

```sh
mkdir -p "${XDG_DATA_HOME:-$HOME/.local/share}/applications"
```

```ini
[Desktop Entry]
Type=Application
Name=Phoenix Rising
Exec=/bin/sh "/home/you/Games/Clan Wars Ubuntu Preview 7 r75/Start Clan Wars Ubuntu.sh"
Terminal=false
Categories=Game;
```

Replace the quoted example with the full path to your installed
`Start Clan Wars Ubuntu.sh`. Keep the double quotes around the path. Desktop
entries need an absolute path, including your actual user name.

Open **Phoenix Rising** from the application menu. To add a desktop icon, copy
the shortcut to your desktop and use your desktop environment’s **Allow
Launching** or trust option if prompted. These launch methods use standard
Linux desktop facilities, including on Steam Deck in Desktop Mode.

## Troubleshooting

If the window fails to open, run the installed launcher again in a terminal
to see the startup output.

```sh
/bin/sh "$HOME/Games/Clan Wars Ubuntu Preview 7 r75/Start Clan Wars Ubuntu.sh"
```

For a game launch failure, use the log path shown in Starter. With the default
data location, look under `~/.local/share/ClanWarsUbuntuStarter/joins/` for
the attempt’s `proton.log`, or under
`~/.local/share/Tribes3CommunityStarter/linux-launches/` for its `bridge.log`.
If your session sets `XDG_DATA_HOME`, use that directory in place of
`~/.local/share`. Steam Snap stores its game-side logs under
`~/snap/steam/common/.local/share/`.

See the [freedesktop Desktop Entry specification](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html)
and the [util-linux setsid manual](https://man7.org/linux/man-pages/man1/setsid.1.html)
for launcher syntax.
