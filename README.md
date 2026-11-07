# TRIBES 3 — Frontend client

## Download and play

**[Download the complete Windows playtest client — r9](https://github.com/T24085/T3FrontEndClient/releases/download/windows-2026.11.07-r9/TRIBES3-Community-Starter-Windows-20261107-r9.zip)** · [Release notes and checksums](https://github.com/T24085/T3FrontEndClient/releases/tag/windows-2026.11.07-r9)

The download includes the Community Starter, portable runtime and all custom map content for the 22-map catalog. No separate map-update ZIPs are needed. You still need your own matching Steam installation of TRIBES 3 Rivals and an approved account on the community's Tailscale network.

r9 restores **Set up server access** in Starter and includes the Heavy Bolt trail fix and final-scoreboard Escape fallback. The refreshed download includes **Damnation (2026)** with reshaped shorelines, animated ripples, and stone footings. All 22 map fingerprints match the shared server. First-time game file verification can take several minutes.

Already on r9? Close Starter and TRIBES 3, extract the updater inside your existing `TRIBES3-Community-Starter` folder, and run `Apply r9 Shoreline Update.bat` from the extracted updater folder. [Download the r9 shoreline updater](https://github.com/T24085/T3FrontEndClient/releases/download/windows-2026.11.07-r9/TRIBES3-Windows-r9-Shoreline-Update.zip)

On r8? Download the refreshed complete r9 ZIP, or apply the r8-to-r9 updater first and then apply the shoreline updater. [Download the r8-to-r9 updater](https://github.com/T24085/T3FrontEndClient/releases/download/windows-2026.11.07-r9/TRIBES3-Windows-r8-to-r9-Update.zip)

1. Download and extract the entire ZIP into a fresh folder.
2. Start Steam and connect to the approved Tailscale network.
3. Open `Start Community Starter.vbs` in the extracted folder.
4. If this device needs access, choose **Set up server access** and use the shared playtest code from your organizer. [Browser setup](https://bigedlaptop.tail5d09b2.ts.net:8443/)

This is a playtest release. The server-side staging-team correction has been deployed; native loopback checks now show both players spawning and populated weapon menus. Off-site confirmation remains open. The double-shot issue is recorded as fixed based on user confirmation. The repository's **Code → Download ZIP** contains development source; use the complete release download above to play.

## Development source

Working source for the community starter UI, game preparation, profiles and client runtime. Paired repository: [T24085/T3BackEndServer](https://github.com/T24085/T3BackEndServer).

The Windows launcher source is desktop_launcher.py / community_starter.pyw; client_entry.py is the canonical packaged CLI entry. Build a private candidate from a separately verified content package before launching a game.

## Source checks

```powershell
python -m pip install -r requirements-dev.txt
python tools/check_source.py
python -m unittest discover -s . -p "test_*.py" -v
```

See [development and release inputs](docs/DEVELOPMENT.md), [current validation and known issues](docs/STATUS.md), and [source provenance](docs/source-baseline.json). Game binaries, packaged runtimes, cooked maps, private configuration and keys are external. No game assets or redistribution license are granted by this source import. Committing or pushing this repository does not update a live server or client.
