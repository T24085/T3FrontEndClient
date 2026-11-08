# TRIBES 3 — Frontend client

## Download and play

**[Download the complete Windows playtest client — r11](https://github.com/T24085/T3FrontEndClient/releases/download/windows-2026.11.07-r11/TRIBES3-Community-Starter-Windows-20261107-r11.zip)** · [Release notes and checksums](https://github.com/T24085/T3FrontEndClient/releases/tag/windows-2026.11.07-r11)

The download includes the Community Starter, portable runtime and all custom map content for the 22-map catalog. You still need your own matching Steam installation of TRIBES 3 Rivals and an approved account on the community's Tailscale network.

r11 reads the host’s map catalog. Compatible new maps show up in the map picker and download in the background. Starter reuses downloaded files and checks the match’s map fingerprint before joining. First-time verification of the original game files can take several minutes.

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
