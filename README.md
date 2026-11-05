# TRIBES 3 — Frontend client

Working source for the community starter UI, game preparation, profiles and client runtime. Paired repository: [T24085/T3BackEndServer](https://github.com/T24085/T3BackEndServer).

The Windows launcher source is desktop_launcher.py / community_starter.pyw; client_entry.py is the canonical packaged CLI entry. Build a private candidate from a separately verified content package before launching a game.

## Source checks

```powershell
python -m pip install -r requirements-dev.txt
python tools/check_source.py
python -m unittest discover -s . -p "test_*.py" -v
```

See [development and release inputs](docs/DEVELOPMENT.md), [current validation and known issues](docs/STATUS.md), and [source provenance](docs/source-baseline.json). Game binaries, packaged runtimes, cooked maps, private configuration and keys are external. No game assets or redistribution license are granted by this source import. Committing or pushing this repository does not update a live server or client.
