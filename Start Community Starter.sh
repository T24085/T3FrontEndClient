#!/bin/sh
set -eu
tribes_package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$tribes_package_dir/linux_launcher.py" "$@"
