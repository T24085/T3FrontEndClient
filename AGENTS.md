# Engineering workflow

This is the working source repository for the TRIBES 3 frontend client. The paired repository is https://github.com/T24085/T3BackEndServer.

Edit this checkout for new work. Legacy research directories and installed packages are reference/deployment inputs, not the development source. Use feature branches for fixes. Preserve source provenance and native process/Job ownership.

Run `python tools/check_source.py` and `python -m unittest discover -s . -p "test_*.py"`. Shared protocol changes must update the paired checkout and shared-contracts.json together; verify with `python tools/check_source.py --peer ../T3BackEndServer`. Never infer native gameplay success from these source checks. Keep game/editor/native qualification isolated and use native_resource_gate.py. Keep secrets, populated connection/configuration files, original game files, large cooked content and native logs outside Git. A Git push is not a deployment.
