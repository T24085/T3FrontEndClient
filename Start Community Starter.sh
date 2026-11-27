#!/bin/sh
set -eu
# Steam may reject the launch before Python or Wine ever starts. Record the
# wrapper entry itself and keep shell and bundled-runtime errors in one place.
case "${1:-}" in
    --steam-launch|--steam-probe)
        umask 077
        state="${XDG_DATA_HOME:-$HOME/.local/share}/Tribes3CommunityStarter"
        mkdir -p -- "$state"
        exec > "$state/launcher-start.log" 2>&1
        printf 'Clan Wars wrapper entered (%s)\n' "$1"
        ;;
esac
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(uname -m)" != x86_64 ]; then
    printf '%s\n' 'Clan Wars requires an x86-64 Linux PC or Steam Deck.' >&2
    exit 1
fi

# The portable runtime is extracted once because its internal Unix links and
# executable bits must survive extraction by Windows-oriented ZIP tools.
bundle="$root/Linux Python.tar.gz"
launcher_python=python3
if [ -f "$bundle" ]; then
    check_file="$root/Linux Python.sha256"
    digest=$(cat "$check_file")
    case "$digest" in
        *[!0123456789abcdef]*|'') printf '%s\n' 'Invalid Python runtime checksum.' >&2; exit 1 ;;
    esac
    [ "${#digest}" -eq 64 ] || exit 1
    runtime="$root/.linux-python/$digest"
    launcher_python="$runtime/python/bin/python3"
    if [ ! -x "$launcher_python" ]; then
        mkdir -p -- "$root/.linux-python"
        temporary=$(mktemp -d "$root/.linux-python/unpacking.XXXXXX")
        trap 'rm -rf -- "$temporary"' EXIT
        actual=$(sha256sum < "$bundle")
        if [ "${actual%% *}" != "$digest" ]; then
            printf '%s\n' 'Bundled Python failed verification. Extract the release archive again.' >&2
            exit 1
        fi
        tar -xzf "$bundle" -C "$temporary"
        test -x "$temporary/python/bin/python3"
        mv -T -n -- "$temporary" "$runtime"
        if [ -d "$temporary" ]; then
            # A concurrent invocation already installed the same verified build.
            "$launcher_python" -I -B -c 'import shutil,sys; shutil.rmtree(sys.argv[1])' "$temporary"
        fi
        trap - EXIT
    fi
fi
case "${1:-}" in
    --ubuntu-native)
        shift
        if [ "$#" -eq 0 ]; then
            exec "$launcher_python" -I -B "$root/ubuntu_startup.py"
        fi
        exec "$launcher_python" -I -B "$root/ubuntu_starter.py" "$@"
        ;;
    --ubuntu-dispatch)
        shift
        exec "$launcher_python" -I -B "$root/ubuntu_starter.py" --dispatch "$@"
        ;;
esac
exec "$launcher_python" -I -B "$root/linux_launcher.py" "$@"
