#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /bin/sh "$root/Start Community Starter.sh" --ubuntu-native "$@"
