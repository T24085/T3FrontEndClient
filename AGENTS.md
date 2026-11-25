# Engineering workflow

This is the working source repository for the TRIBES 3 frontend client. The paired repository is https://github.com/T24085/T3BackEndServer.

Edit this checkout for new work. Legacy research directories and installed packages are reference/deployment inputs, not the development source. Use feature branches for fixes. Preserve source provenance and native process/Job ownership.

## GitHub coordination

- Before editing, check [active work in this repo](https://github.com/T24085/T3FrontEndClient/issues?q=is%3Aissue+is%3Aopen+label%3A%22in+progress%22) and the [paired repo](https://github.com/T24085/T3BackEndServer/issues?q=is%3Aissue+is%3Aopen+label%3A%22in+progress%22). Reuse the relevant issue or open one if needed. Coordinate overlapping work on the issue before editing the same area.
- Claim the issue with the `in progress` label. Post the owner or agent identifier, scope, branch, and start date and time in Central Time. Link the paired issue for work that spans both repos.
- Update the issue when the scope or status changes, when blocked, and at handoff. Include the branch, commit or PR, verification results, and what is still pending. Remove `in progress` when active work stops. Match the visibility of the repo when sharing details, and keep credentials out of issues.

## Live server approval

Commit the source in the relevant repos and verify the push on GitHub first. Then send Chris the issue and commit or PR links, the target server, what would go live, the verification results, and any restart or player impact. Wait for his explicit approval for that deployment before uploading, staging, or applying changes on a live server or restarting it. Follow the approved scope and timing, and record the approval and live verification on the issue.

Run `python tools/check_source.py` and `python -m unittest discover -s . -p "test_*.py"`. Shared protocol changes must update the paired checkout and shared-contracts.json together; verify with `python tools/check_source.py --peer ../T3BackEndServer`. Never infer native gameplay success from these source checks. Keep game/editor/native qualification isolated and use native_resource_gate.py. Keep secrets, populated connection/configuration files, original game files, large cooked content and native logs outside Git. A Git push is not a deployment.

The public Windows release includes Lobbies, Live matches, Public CTF, and Armor. Put `Start Clan Wars.bat` at the top level of the ZIP. Verify the exact archive with a fresh device profile against the live service before publishing. A Public CTF-only release requires an explicit request.
