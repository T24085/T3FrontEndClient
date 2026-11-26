# Publishing Community Starter updates

The complete Windows r12 ZIP installs the updater. Players open the same Starter shortcut for later updates. The trusted bootstrap and public key ship with r12. The signing key lives in the release operator's Current User certificate store.

With PowerShell 7 installed, build an update from a clean source commit with `python tools/build_starter_update.py --output <outside-checkout> --certificate <thumbprint> --previous <last-signed-index> lua/client.lua`. The first update omits `--previous`. The tool carries forward every previously managed path from the current source tree. Include newly managed paths on the command line. A patch can restore a file by publishing its earlier bytes as a newer revision.

Publish `starter-file-<sha256>.bin` assets on the GitHub `starter-updates-v1` release before replacing `starter-update.json`. Reuse identical existing assets. Verify the provider digests and the public index after upload. Keep the preceding index and its referenced files available during publishing. The index expires 90 days after signing. Renew it with a new revision even when the client files are identical.

The r12 channel covers the allowlisted Python and Lua paths in `starter_update.py`. A build that changes the bootstrap, packaged Python runtime, or map fingerprint runtime still needs a complete ZIP. Compatible cooked map updates use the existing server catalog. Test updates with a disposable r12 install and preserve the `.starter-update/previous` backup when debugging startup failures.

## Windows Direct Starter

The Direct package builder installs the signed updater. Players switch once to a group ZIP with the host-backed updater. After that, they open `Start Direct Starter.bat` as usual. The launcher downloads updates over HTTPS from the host in its invitation. It verifies them with the same release signing key as the regular Starter. The friend host also serves compatible maps.

Build Direct updates with `--channel windows-direct-r12-v1`. When supplying `--previous`, use the last signed Direct index. The Direct channel also accepts `direct_client.py` and `direct_network.py` from `experimental/direct-hosting/src`. Coordinate any direct protocol changes with the host release.

Publish the signed artifacts to `operator/direct-local/starter-updates` on the friend host. Upload and verify the content files first, then replace `starter-update.json` atomically using a temporary file in that directory. Keep the previous index and its content files available during the change. The running host serves the new index on the next request. Keep the private signing key on the release operator's machine.

## Full Windows Clan Wars ZIP

Use the full Windows Direct Starter ZIP as the base when reissuing the download
with its existing maps. Pin its SHA-256 from a verified release receipt.

```powershell
python tools/windows_starter_release.py build --base "<verified full ZIP>" --base-sha256 <sha256> --output "<new full ZIP>"
python tools/windows_starter_release.py verify "<new full ZIP>"
```

The builder uses the host in the packaged invitation. It verifies the current
signed index and embeds its files and revision before first launch. It checks
the feed again after writing the ZIP and rejects the build if the live revision
changed during packaging. The Windows/Proton wrapper performs the same
revision and managed-file check before finalizing its ZIP.

Run the verify command again immediately before sharing a ZIP. Extract that
exact archive and run the top-level BAT with a fresh device profile. Confirm
the bundled revision, private lobby and Live Matches access, and the live map
catalog using the packaged client. On hosts that advertise per-map sync,
check that the client reads the catalog and prepares the selected map through
that path. Include the archive name, hash, revision, and qualification result
in the release notes. Use the verified archive as the download players see
when they install for the first time.

## Map-declared music

A map can set `music = {track = "t2-desert"}` in its verified `objectives.lua`.
Use `music = {playlist = "t1", first = 8}` to play the existing T1 playlist
starting at track 8. The client selects a track when gameplay starts and
releases it at match end or travel.

For cooked tracks, use the shared sound pack format in
[backend PR #99](https://github.com/Tribes3-Modded/T3BackEndServer/pull/99).
In a full client package, keep the Map Tool's directory layout under
`Client Files/sound-packs/`. Put the metadata files in the verified client
inventory.

- Game pack files live at `sound-packs/<SET>/pack.json`.
- Per-map overrides live at `sound-packs/maps/<MapId>/override.json`.

Use `music = {track = "music.match"}` in `objectives.lua` to select the
match binding. The client resolves the map override, the selected `sound_set`
pack, and the T3 fallback pack in that order. A map may also declare a music
event ID exported by the Map Tool. A single-wave event and its loop wrapper
can play directly. Cook more elaborate graphs into a Sound Cue and link the
cue with an `asset` binding. The cooked Sound Cue or Sound Wave must route its
base output to `MUS_Game_Submix`. Set looping on the cooked asset for continuous
music.

The signed Windows Direct feed can also resolve the legacy MP3 tracks by
their existing SHA-256 addresses. The signed builder embeds their addresses
and the player code, and updates the Python entry and Lua template together.
