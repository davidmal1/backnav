#!/usr/bin/env bash
# Regenerate the extension icons from the two SVG sources.
#
# Two sources, not one, deliberately: the three-row artwork smears into an
# illegible block below about 48px, so the small sizes use a simplified
# drawing with two chunkier rows and a larger arrow. Rendered and compared
# side by side at 4x before choosing the crossover point.
set -euo pipefail
cd "$(dirname "$0")"
root=".."

for build in chromium firefox thunderbird; do
    out="$root/$build/icons"
    mkdir -p "$out"

    for size in 16 32; do
        inkscape icon-small.svg -w "$size" -h "$size" -o "$out/icon-$size.png" >/dev/null 2>&1
    done

    for size in 48 96 128; do
        inkscape icon.svg -w "$size" -h "$size" -o "$out/icon-$size.png" >/dev/null 2>&1
    done

    echo "$build: $(ls "$out" | tr '\n' ' ')"
done
