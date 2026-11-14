#!/bin/sh
set -eu
clan_wars_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$clan_wars_dir/Client Files/linux_launcher.py" "$@"
