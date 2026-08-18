#!/usr/bin/env bash
#
# Package a Gecko build as an installable .xpi.
#
# An .xpi is just a zip with the manifest at its root - there is no
# tooling to install and nothing to sign for Thunderbird, which accepts
# unsigned add-ons (confirmed live 2026-08-18: installed from file and
# survived a restart, keeping its instanceId because the gecko.id
# matched, so it upgraded the temporary add-on rather than sitting
# alongside it).
#
# Firefox is NOT the same. Release Firefox compiles signature enforcement
# in and ignores xpinstall.signatures.required, so an unsigned .xpi built
# here will be refused. Build it, then get it signed by AMO - either as a
# listing or via self-distribution, which returns a signed .xpi to host
# yourself - and install that.
#
# Usage: ./build-xpi.sh [thunderbird|firefox]   (default: thunderbird)
set -euo pipefail

cd "$(dirname "$0")"

build="${1:-thunderbird}"

case "$build" in
    thunderbird|firefox) ;;
    *) echo "usage: $0 [thunderbird|firefox]" >&2; exit 1 ;;
esac

version=$(python3 -c "import json;print(json.load(open('$build/manifest.json'))['version'])")
out="$PWD/backnav-$build-$version.xpi"

rm -f "$out"

# Zipped from INSIDE the build directory: the manifest has to sit at the
# root of the archive, not under a folder, or the add-on will not load.
( cd "$build" && zip -r -X "$out" manifest.json background.js icons >/dev/null )

echo "$out"
unzip -l "$out" | tail -3

if [ "$build" = "firefox" ]; then
    echo
    echo "NOTE: unsigned. Release Firefox will refuse this - get it signed"
    echo "      by AMO first. Thunderbird needs no signing."
fi
