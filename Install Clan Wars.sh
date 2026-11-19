#!/bin/sh
set -eu
package=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /bin/sh "$package/Start Community Starter.sh" --guided-install "$@"
