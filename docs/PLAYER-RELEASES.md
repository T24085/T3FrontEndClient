# Complete player releases

Players download the complete Windows ZIP from the repository's Releases section. It contains the launcher/runtime and all authored map payloads required by its map catalog. Native TRIBES 3 maps still come from the player's own matching Steam installation. The source-code ZIP is for development.

The first GitHub player release is `windows-2026.11.04-r5`, retaining the existing complete Windows r5 artifact. It is a playtest prerelease because multiplayer join and loadout-menu defects remain open. Publishing it does not deploy a server fix.

## Verify before publishing

Use a fresh read-only `map_catalog.verified_catalog(host_package)` result from the intended server. Save an object containing `verified_map_catalog` and `host_manifest_sha256` outside Git. Then run:

```powershell
python tools/verify_player_release.py --archive <complete-client.zip> --server-catalog <verified-server-catalog.json> --output <verification-output>
```

The verifier checks ZIP framing and inventory, streams SHA-256 over every member, checks packaged Python syntax, rejects original-game archives and private keys, and compares every map fingerprint with the server. Its fingerprint format is tested against the existing directory verifier. It also writes `VERIFICATION.json` and `MAP-CATALOG.json`; publish these alongside the archive and its SHA-256 checksum file.

Release assets must each remain below GitHub's 2 GiB limit. If a future complete client exceeds that, design and verify a versioned installer/map-pack download before changing the player instructions; do not silently omit maps.

## Source and artifact provenance

The r5 ZIP was built before these repositories were created. Its embedded `RELEASE-INFO.json` and package manifest retain its original build identity. The Git tag records this distribution/verification setup, not a claim that the old ZIP was rebuilt byte-for-byte from the tag. `DISTRIBUTION-PROVENANCE.json` records the archive digest, its original package-manifest digest and the corresponding frontend/backend source references.

Later releases should record the exact source commits used to build their packages. Update shared runtime/catalog files and both repositories' shared-contracts.json together. Verify all selected map hashes against the target server again for each release. Keep download links pinned to a verified release rather than an unverified development branch.

## Building a current complete release

`tools/build_player_release.py` takes an externally retained base archive and its exact SHA256, a fresh verified server catalog, the paired backend checkout, and a fresh output directory outside the source checkout. It retains cooked content, map-fingerprint runtime and bundled binary bytes from the verified base. Canonical client source overlays and updated instructions are inventoried; `SOURCE-INFO.json` records their hashes and exact source commits. Both selected checkouts must be clean and committed before building, and remain unchanged during the build.

Run the complete archive verifier above afterward. A published client release does not deploy the server. Keep unresolved multiplayer/loadout and cold-preparation limitations explicit in playtest release notes.
