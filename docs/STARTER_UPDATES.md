# Publishing Community Starter updates

The complete Windows r12 ZIP installs the updater. Players open the same Starter shortcut for later updates. The trusted bootstrap and public key ship with r12. The signing key lives in the release operator's Current User certificate store.

With PowerShell 7 installed, build an update from a clean source commit with `python tools/build_starter_update.py --output <outside-checkout> --certificate <thumbprint> --previous <last-signed-index> lua/client.lua`. The first update omits `--previous`. The tool carries forward every previously managed path from the current source tree. Include newly managed paths on the command line. A patch can restore a file by publishing its earlier bytes as a newer revision.

Publish `starter-file-<sha256>.bin` assets on the GitHub `starter-updates-v1` release before replacing `starter-update.json`. Reuse identical existing assets. Verify the provider digests and the public index after upload. Keep the preceding index and its referenced files available during publishing. The index expires 90 days after signing. Renew it with a new revision even when the client files are identical.

The r12 channel covers the allowlisted Python and Lua paths in `starter_update.py`. A build that changes the bootstrap, packaged Python runtime, or map fingerprint runtime still needs a complete ZIP. Compatible cooked map updates use the existing server catalog. Test updates with a disposable r12 install and preserve the `.starter-update/previous` backup when debugging startup failures.

## Windows Direct Starter

The Direct package builder installs the signed updater. Players switch once to a group ZIP with the host-backed updater. After that, they open `Start Direct Starter.bat` as usual. The launcher downloads updates over HTTPS from the host in its invitation. It verifies them with the same release signing key as the regular Starter. The friend host also serves compatible maps.

Build Direct updates with `--channel windows-direct-r12-v1`. When supplying `--previous`, use the last signed Direct index. The Direct channel also accepts `direct_client.py` and `direct_network.py` from `experimental/direct-hosting/src`. Coordinate any direct protocol changes with the host release.

Publish the signed artifacts to `operator/direct-local/starter-updates` on the friend host. Upload and verify the content files first, then replace `starter-update.json` atomically using a temporary file in that directory. Keep the previous index and its content files available during the change. The running host serves the new index on the next request. Keep the private signing key on the release operator's machine.

## Linux Direct Starter

Preview 6 r74 can enable automatic updates with the one-time shell script.
Create it with `python tools/build_ubuntu_update.py enable <preview6.run> <output.sh>`.
Linux installers from Preview 7 onward include the bootstrap. Normal desktop
startup checks the Linux feed, defers updates during a game session, and keeps
the existing Steam launch option. It verifies the same release signing key
through Ubuntu's OpenSSL and restores the previous runtime if startup fails.

To prepare a release, run `python tools/build_ubuntu_update.py feed <preview6.run> <output-directory> --signed-snapshot <verified-windows-snapshot> --revision <linux-revision> --certificate <thumbprint>`.
Increment the Linux revision independently. The build carries forward the
signed Windows Direct runtime, retains the Proton compatibility overlay, and
adds the native Ubuntu modules. Upload and verify the content files in the
same host directory before replacing `starter-linux-update.json` atomically.
Renew the Linux index before its
120-day expiration. Use a full installer or a separate bootstrap repair for
changes to the updater itself.
