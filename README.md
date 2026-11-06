# TRIBES 3 — Frontend client

## Download and play

**[Download the complete Windows playtest client — r6](https://github.com/T24085/T3FrontEndClient/releases/download/windows-2026.11.06-r7/TRIBES3-Community-Starter-Windows-20261106-r7.zip)** · [Release notes and checksums](https://github.com/T24085/T3FrontEndClient/releases/tag/windows-2026.11.06-r7)

The download includes the Community Starter, portable runtime and all custom map content for the 22-map catalog. No separate map-update ZIPs are needed. You still need your own matching Steam installation of TRIBES 3 Rivals and an approved account on the community's Tailscale network.

R7 includes the Heavy Bolt trail correction for shots still airborne after switching weapons; visible whiteout resolution still needs player confirmation. The paired server has the Katabatic turret and flag-return updates. R6 lobby recovery, stable refresh controls, parallel preparation and first-person spectator features are retained. First verification can take minutes; warm preparation is not guaranteed to finish in 6–10 seconds.

1. Download and extract the entire ZIP into a fresh folder.
2. Start Steam and connect to the approved Tailscale network.
3. Open `Start Community Starter.vbs` in the extracted folder.

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
