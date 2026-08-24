#!/usr/bin/env bash
#
# Install BackNav: dependencies, both KWin scripts, and the daemon as a
# user service.
#
# Safe to re-run. Every step upgrades in place rather than failing on a
# second pass, because the usual reason to run this twice is that
# something went wrong the first time.
#
# What it deliberately does NOT do:
#
#   - bind the shortcut. Which key you want is a real choice, and Alt+Tab
#     specifically collides with KWin's own switcher, which KDE has to ask
#     you about. Doing that silently would be rude and probably wrong.
#   - install the browser extensions. Those are per-browser and some need
#     a click in the browser's own UI.
#   - generate the Thunderbird certificate. Only matters if you use
#     Thunderbird, and it needs a per-profile exception afterwards that
#     nothing can automate.
#
# All three are printed at the end.

set -euo pipefail

readonly REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly UNIT="$HOME/.config/systemd/user/backnav.service"
# The interpreter the SERVICE will use, which is not necessarily the one
# running this script. /usr/bin/python3 is right when the dependencies
# come from apt, as below. Override it if you keep them in a virtualenv:
#
#   BACKNAV_PYTHON=/path/to/venv/bin/python3 ./install.sh
#
# systemd starts the unit without your shell, so an activated venv is not
# inherited and the unit has to name the interpreter outright.
readonly PYTHON="${BACKNAV_PYTHON:-/usr/bin/python3}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- refuse the obviously wrong context -------------------------------

# Everything here lands in $HOME - a user systemd unit, a user KWin
# package, a user config file. Run under sudo it would install for root
# and appear to do nothing.
[ "$(id -u)" -ne 0 ] || die "Do not run this with sudo. It installs into your own home directory; it will ask for sudo only for the apt line."

[ -f "$REPO/backnav-engine/backnav.py" ] || die "Run this from inside the backnav repository (looked in $REPO)."

# ---- environment, warned about rather than enforced -------------------

# Warnings, not failures. Someone testing on a session this was not
# written for should be allowed to find out for themselves.
say "Checking the session"

if [ "${XDG_SESSION_TYPE:-}" != "wayland" ]; then
    note "WARNING: session type is '${XDG_SESSION_TYPE:-unknown}', not wayland."
    note "         BackNav is developed and tested on Plasma 6 Wayland only."
else
    note "Wayland session: yes"
fi

if command -v plasmashell >/dev/null 2>&1; then
    note "Plasma: $(plasmashell --version 2>/dev/null | head -1)"
else
    note "WARNING: plasmashell not found - is this KDE Plasma?"
fi

command -v kpackagetool6 >/dev/null 2>&1 || die "kpackagetool6 not found. It ships with Plasma 6; on Ubuntu it is in the 'kde-cli-tools' or plasma packages."

# ---- dependencies ------------------------------------------------------

say "Checking Python dependencies"

# Checked against /usr/bin/python3 specifically, because that is the
# interpreter the systemd unit will name. A virtualenv that happens to be
# active in this shell is irrelevant to a service systemd starts.
missing=()

for module in websockets dbus_next; do
    if "$PYTHON" -c "import $module" 2>/dev/null; then
        note "$module: present"
    else
        note "$module: MISSING"
        missing+=("$module")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    if ! command -v apt-get >/dev/null 2>&1; then
        die "Missing Python modules: ${missing[*]}. This script installs them with apt; on other distributions install the equivalents (python3-websockets, python3-dbus-next) and re-run."
    fi

    # apt rather than pip, and not as a preference: Ubuntu 24.04 and later
    # ship Python as an externally managed environment, so pip into the
    # system refuses outright and tells you to use the package manager.
    say "Installing them with apt (this needs sudo)"

    sudo apt-get install -y python3-websockets python3-dbus-next

    for module in "${missing[@]}"; do
        "$PYTHON" -c "import $module" 2>/dev/null \
            || die "$module still not importable by $PYTHON after installing. Something is unusual about this Python setup; see the README's note about virtualenvs."
    done

    note "Both modules now importable by $PYTHON"
fi

# ---- the KWin scripts --------------------------------------------------

say "Installing the KWin scripts"

# -i on an installed package is an error, -u on a missing one is too, so
# ask first. This is what makes the script re-runnable.
installed="$(kpackagetool6 --type KWin/Script --list 2>/dev/null || true)"

# Package id -> the directory it is built from. The ids are NOT the
# directory names: the event producer's package is "backnav", one
# character from the project's own name, which is worth reading twice
# before typing either into kpackagetool6.
for pair in "backnav:backnav-kwin" "backnav-overlay:backnav-kwin-overlay"; do
    pkg="${pair%%:*}"
    src="$REPO/${pair##*:}"

    [ -d "$src" ] || die "Missing $src - is the clone complete?"

    if printf '%s\n' "$installed" | grep -qx "$pkg"; then
        kpackagetool6 --type KWin/Script -u "$src" >/dev/null
        note "$pkg: upgraded"
    else
        kpackagetool6 --type KWin/Script -i "$src" >/dev/null
        note "$pkg: installed"
    fi
done

# ---- enable them -------------------------------------------------------

say "Enabling them"

# Installing a KWin script does not switch it on; that is a separate flag
# in kwinrc, which is what the checkbox in System Settings writes.
kwriteconfig6 --file kwinrc --group Plugins --key backnavEnabled true
kwriteconfig6 --file kwinrc --group Plugins --key backnav-overlayEnabled true

note "backnavEnabled=true, backnav-overlayEnabled=true in kwinrc"

# Tell the running KWin to re-read that, so this takes effect now rather
# than at next login.
if qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1; then
    note "KWin reconfigured"
else
    note "Could not reach KWin over D-Bus - log out and back in to load them."
fi

# ---- the daemon as a user service --------------------------------------

say "Setting up the daemon service"

mkdir -p "$(dirname "$UNIT")"

# Keep a copy of anything already there. A hand-edited unit is somebody's
# work - most likely an ExecStart pointing at a virtualenv - and silently
# overwriting it would be the kind of thing you discover much later.
if [ -f "$UNIT" ]; then
    cp -f "$UNIT" "$UNIT.bak"
    note "Existing unit backed up to $UNIT.bak"
fi

# Absolute paths throughout: systemd does not expand ~, and a unit that
# used it fails with "bad unit file setting", which names neither the
# setting nor the reason.
cat > "$UNIT" <<UNITFILE
[Unit]
Description=BackNav navigation daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=$PYTHON $REPO/backnav-engine/backnav.py
WorkingDirectory=$REPO/backnav-engine
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
UNITFILE

note "Wrote $UNIT"

systemctl --user daemon-reload
systemctl --user enable --now backnav >/dev/null 2>&1 || true
systemctl --user restart backnav

# ---- did it actually come up? ------------------------------------------

say "Checking it started"

for _ in $(seq 1 10); do
    if systemctl --user is-active --quiet backnav; then break; fi
    sleep 0.5
done

if systemctl --user is-active --quiet backnav; then
    note "Service: active"
    listening="$(journalctl --user -u backnav -n 20 -o cat 2>/dev/null | grep -m1 'WebSocket listening' || true)"
    [ -n "$listening" ] && note "$listening"
else
    printf '\n'
    systemctl --user status backnav --no-pager | head -20
    die "The daemon did not start. Its output is above; 'journalctl --user -u backnav' has the rest."
fi

# ---- what is left, which is the part a script should not guess ---------

cat <<'DONE'

==> Installed. Three things left, none of which this script should decide
    for you:

 1. BIND THE SHORTCUT. Nothing works until you do.

    System Settings -> Keyboard -> Shortcuts, search for "BackNav",
    and give "BackNav: Navigate Back" a key. Meta+Tab is uncontested.
    Alt+Tab works too, but KWin already owns it and will ask you to
    confirm taking it away from the built-in switcher.

 2. BROWSER EXTENSIONS, for tab-level navigation. Without one, a browser
    is a single entry rather than one per tab. See the README section
    "Installing the browser extensions" - Chrome, Brave, Vivaldi and
    Opera load browser/chromium/ unpacked; Firefox installs a signed
    file from the releases page.

 3. ONLY IF YOU USE kitty, qpdfview OR Thunderbird, each needs one
    one-time setting - remote control, "Restore tabs", and a TLS
    certificate respectively. The README has a short section for each.

    Watch what it is seeing:  journalctl --user -u backnav -f

DONE
