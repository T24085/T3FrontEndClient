# Publishing Community Starter updates

The complete Windows r12 ZIP installs the updater. Players open the same Starter shortcut for later updates. The trusted bootstrap and public key ship with r12. The signing key lives in the release operator's Current User certificate store.

With PowerShell 7 installed, build an update from a clean source commit with `python tools/build_starter_update.py --output <outside-checkout> --certificate <thumbprint> --previous <last-signed-index> lua/client.lua`. The first update omits `--previous`. The tool carries forward every previously managed path from the current source tree. Include newly managed paths on the command line. A patch can restore a file by publishing its earlier bytes as a newer revision.

Publish `starter-file-<sha256>.bin` assets on the GitHub `starter-updates-v1` release before replacing `starter-update.json`. Reuse identical existing assets. Verify the provider digests and the public index after upload. Keep the preceding index and its referenced files available during publishing. The index expires 90 days after signing. Renew it with a new revision even when the client files are identical.

The r12 channel covers the allowlisted Python and Lua paths in `starter_update.py`. A build that changes the bootstrap, packaged Python runtime, or map fingerprint runtime still needs a complete ZIP. Compatible cooked map updates use the existing server catalog. Test updates with a disposable r12 install and preserve the `.starter-update/previous` backup when debugging startup failures.

## Windows Direct Starter

The Direct package builder installs the signed updater. Existing Direct r12 folders need the bootstrap update once. After that, players open `Start Direct Starter.bat` as usual. The update feed uses the same signing key with its own channel and release tag. Host invitations stay in the player ZIP, and the friend host continues to serve compatible maps.

Build Direct updates with `--channel windows-direct-r12-v1` and publish them on the GitHub release tagged `direct-starter-updates-v1`. When supplying `--previous`, use the last signed Direct index. The Direct channel also accepts `direct_client.py` and `direct_network.py` from `experimental/direct-hosting/src`. Coordinate any direct protocol changes with the host release.
