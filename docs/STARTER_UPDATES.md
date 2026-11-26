# Publishing Community Starter updates

The complete Windows r12 ZIP installs the updater. Players open the same Starter shortcut for later updates. The trusted bootstrap and public key ship with r12. The signing key lives in the release operator's Current User certificate store.

With PowerShell 7 installed, build an update from a clean source commit with `python tools/build_starter_update.py --output <outside-checkout> --certificate <thumbprint> --previous <last-signed-index> lua/client.lua`. The first update omits `--previous`. The tool carries forward every previously managed path from the current source tree. Include newly managed paths on the command line. A patch can restore a file by publishing its earlier bytes as a newer revision.

Publish `starter-file-<sha256>.bin` assets on the GitHub `starter-updates-v1` release before replacing `starter-update.json`. Reuse identical existing assets. Verify the provider digests and the public index after upload. Keep the preceding index and its referenced files available during publishing. The index expires 90 days after signing. Renew it with a new revision even when the client files are identical.

The r12 channel covers the allowlisted Python and Lua paths in `starter_update.py`. A build that changes the bootstrap, packaged Python runtime, or map fingerprint runtime still needs a complete ZIP. Compatible cooked map updates use the existing server catalog. Test updates with a disposable r12 install and preserve the `.starter-update/previous` backup when debugging startup failures.

## Windows Direct Starter

The Direct package builder installs the signed updater. Players switch once to a group ZIP with the host-backed updater. After that, they open `Start Direct Starter.bat` as usual. The launcher downloads updates over HTTPS from the host in its invitation. It verifies them with the same release signing key as the regular Starter. The friend host also serves compatible maps.

Build Direct updates with `--channel windows-direct-r12-v1`. When supplying `--previous`, use the last signed Direct index. The Direct channel also accepts `direct_client.py` and `direct_network.py` from `experimental/direct-hosting/src`. Coordinate any direct protocol changes with the host release.

Publish the signed artifacts to `operator/direct-local/starter-updates` on the friend host. Upload and verify the content files first, then replace `starter-update.json` atomically using a temporary file in that directory. Keep the previous index and its content files available during the change. The running host serves the new index on the next request. Keep the private signing key on the release operator's machine.

For the public Direct feed, qualify the candidate update on a copy of the
current installer with a fresh device profile before publishing. Use a host
that advertises per-session map sync and has a catalog with more than 10,000
cooked files. Confirm Starter opens, the Maps list loads, and entering a match
verifies and prepares the selected map through per-session sync. A valid
signature and a higher revision alone do not test this. Follow
[issue #89](https://github.com/Tribes3-Modded/T3FrontEndClient/issues/89) for
the per-session runtime reconciliation with `main`.

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

After replacing a shared Drive ZIP, download it from the same player-facing
URL while signed out. Verify the download against the SHA-256 recorded during
qualification and the current signed feed before announcing the release.

```powershell
python tools/windows_starter_release.py verify "<downloaded public ZIP>" --sha256 <qualified-zip-sha256>
```
