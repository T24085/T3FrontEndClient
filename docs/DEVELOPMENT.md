# Development and releases

Use Python 3.13. Install test dependencies with `python -m pip install -r requirements-dev.txt`. Run `python tools/check_source.py` and `python -m unittest discover -s . -p "test_*.py" -v`. These checks use synthetic data and loopback HTTP fixtures; they do not launch the original game.

Clone the paired repository alongside this checkout. The modules listed in shared-contracts.json are intentionally duplicated while the projects are split. Change both copies and their contract hashes in coordinated commits, then run `python tools/check_source.py --peer ../T3BackEndServer`. Keep the direct-network adapter identical in both experimental folders as well.

Use a feature branch for a fix, commit its focused tests and validation scope, and open a PR when review is useful. Record source commit IDs for both repositories in each release's provenance. Do not edit an installed package as the only copy of a fix.

The original Steam installation, verified host/client content packages, portable Python/Tk runtime, UE4SS binaries, cooked map payloads, TLS keys and populated configuration stay outside Git. Existing builders consume explicitly supplied verified package paths and SHA-256 manifests. Some historical default paths still refer to the research workstation; provide explicit --source/--output paths. The Windows desktop builder also expects its external runtime-sources prerequisites. This is a source baseline, not a fresh game installation or a claim that a clone alone can launch a match.

The backend builder requires both an external host package and matching frontend package. Matching cooked-map fingerprints, protocol versions and native qualification are release requirements. GitHub source checks do not deploy either component.
