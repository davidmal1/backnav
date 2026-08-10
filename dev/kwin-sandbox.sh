#!/usr/bin/env bash
#
# kwin-sandbox.sh - an isolated, disposable KWin session for developing and
# testing BackNav's KWin scripts (backnav-kwin/, backnav-kwin-overlay/)
# without touching your real, live KWin session.
#
# Why this exists: a live test of backnav-kwin-overlay caused a real
# incident on the developer's actual desktop (visual corruption + a flood
# of window-closed events, see git history around 2026-08-10). Testing
# KWin scripts against `org.kde.KWin` on your normal session bus means
# mistakes land on windows you're actually using. This script instead:
#
#   1. Runs a nested `kwin_wayland` instance in its own 1024x768 window
#      (KWin's own supported "windowed mode", same thing KWin's upstream
#      devs use to test KWin itself).
#   2. Launches it under `dbus-run-session`, giving it a brand new private
#      D-Bus session bus - so the nested instance's `org.kde.KWin` service
#      name can NEVER collide with, or be confused for, your real
#      session's `org.kde.KWin`. Every command below only ever talks to
#      the sandbox bus, explicitly.
#
# Confirmed live: with this isolation in place, `qdbus6 ...
# org.kde.kwin.Scripting.loadDeclarativeScript <path> <pluginName>` is the
# correct way to load a declarativescript-mode package's QML directly (the
# plain `loadScript` method force-parses the file as JavaScript and fails
# on QML's `import` line; `loadDeclarativeScript` does not have this
# problem). See backnav-kwin-overlay/README.md for the wider design notes.
#
# Usage:
#   dev/kwin-sandbox.sh start [width] [height]   # default 1024x768
#   dev/kwin-sandbox.sh stop
#   dev/kwin-sandbox.sh status
#   dev/kwin-sandbox.sh env                      # eval "$(dev/kwin-sandbox.sh env)"
#   dev/kwin-sandbox.sh qdbus <qdbus6 args...>    # qdbus6 against the sandbox bus
#   dev/kwin-sandbox.sh exec <command...>         # run anything with the sandbox bus exported
#   dev/kwin-sandbox.sh load <qml-file> [pluginName]     # loadDeclarativeScript
#   dev/kwin-sandbox.sh load-js <js-file> [pluginName]   # loadScript (plain JS packages)
#   dev/kwin-sandbox.sh unload <pluginName>
#   dev/kwin-sandbox.sh fake-nav start [state.json]      # fake com.backnav.Navigator
#   dev/kwin-sandbox.sh fake-nav stop
#   dev/kwin-sandbox.sh daemon start                     # the REAL backnav-engine daemon
#   dev/kwin-sandbox.sh daemon stop
#   dev/kwin-sandbox.sh logs [kwin|fakenav|daemon] [-f]
#
# Typical overlay dev loop:
#   dev/kwin-sandbox.sh start
#   dev/kwin-sandbox.sh fake-nav start
#   dev/kwin-sandbox.sh load backnav-kwin-overlay/contents/ui/main.qml backnav-overlay-dev
#   dev/kwin-sandbox.sh logs kwin -f     # watch for errors while you iterate
#   ...edit main.qml...
#   dev/kwin-sandbox.sh unload backnav-overlay-dev
#   dev/kwin-sandbox.sh load backnav-kwin-overlay/contents/ui/main.qml backnav-overlay-dev
#   dev/kwin-sandbox.sh stop
#
# Nothing here ever reads or writes your real session's `org.kde.KWin` or
# `com.backnav.Navigator`. `daemon start` is the one partial exception:
# it runs the real backnav-engine daemon.py, which internally follows
# `journalctl --user -u plasma-kwin_wayland.service` (your REAL session's
# systemd unit) for focus/caption/closed events, since the nested sandbox
# instance isn't a systemd unit and has no windows of its own anyway. That
# journalctl read is read-only and harmless, but it means daemon-sourced
# history will reflect your real desktop's windows, not the sandbox's.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEV_DIR="$REPO_ROOT/dev"
STATE_DIR="${XDG_RUNTIME_DIR:-/tmp}/backnav-sandbox"
SOCKET_NAME="wayland-backnav-sandbox"

PYTHON="${BACKNAV_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x "$HOME/.venv/bin/python3" ]; then
        PYTHON="$HOME/.venv/bin/python3"
    else
        PYTHON="python3"
    fi
fi

mkdir -p "$STATE_DIR"

is_alive() {
    [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

pid_file_alive() {
    local f="$STATE_DIR/$1"
    [ -f "$f" ] && is_alive "$(cat "$f")"
}

sandbox_running() {
    pid_file_alive kwin.pid
}

require_running() {
    if ! sandbox_running; then
        echo "sandbox is not running - start it first with: $0 start" >&2
        exit 1
    fi
}

bus_address() {
    cat "$STATE_DIR/dbus.env"
}

cmd_start() {
    local width="${1:-1024}"
    local height="${2:-768}"

    if sandbox_running; then
        echo "sandbox already running (kwin pid $(cat "$STATE_DIR/kwin.pid")); use 'status' or 'stop'" >&2
        exit 1
    fi

    rm -f "$STATE_DIR"/*.pid "$STATE_DIR/dbus.env"
    : > "$STATE_DIR/kwin.log"

    (
        dbus-run-session -- bash -c '
            echo $$ > "'"$STATE_DIR"'/shell.pid"
            echo -n "$DBUS_SESSION_BUS_ADDRESS" > "'"$STATE_DIR"'/dbus.env"
            kwin_wayland --width "'"$width"'" --height "'"$height"'" --socket "'"$SOCKET_NAME"'" \
                > "'"$STATE_DIR"'/kwin.log" 2>&1 &
            echo $! > "'"$STATE_DIR"'/kwin.pid"
            wait
        '
    ) > "$STATE_DIR/dbus-daemon.log" 2>&1 &
    echo $! > "$STATE_DIR/launcher.pid"

    echo -n "waiting for sandbox KWin to come up"
    for _ in $(seq 1 50); do
        if [ -f "$STATE_DIR/dbus.env" ] && [ -f "$STATE_DIR/kwin.pid" ] \
            && is_alive "$(cat "$STATE_DIR/kwin.pid")" \
            && DBUS_SESSION_BUS_ADDRESS="$(bus_address)" qdbus6 org.kde.KWin >/dev/null 2>&1; then
            echo " ready."
            echo "kwin pid:    $(cat "$STATE_DIR/kwin.pid")"
            echo "bus address: $(bus_address)"
            echo "(run: eval \"\$($0 env)\"  -- to point your own shell's qdbus6/tools at it)"
            return 0
        fi
        echo -n "."
        sleep 0.2
    done

    echo " failed."
    echo "--- kwin.log ---"
    cat "$STATE_DIR/kwin.log" >&2 || true
    cmd_stop || true
    exit 1
}

cmd_stop() {
    if ! sandbox_running && ! pid_file_alive fakenav.pid && ! pid_file_alive daemon.pid; then
        echo "sandbox is not running"
        return 0
    fi

    if pid_file_alive daemon.pid; then
        kill "$(cat "$STATE_DIR/daemon.pid")" 2>/dev/null || true
    fi
    if pid_file_alive fakenav.pid; then
        kill "$(cat "$STATE_DIR/fakenav.pid")" 2>/dev/null || true
    fi
    if pid_file_alive kwin.pid; then
        kill "$(cat "$STATE_DIR/kwin.pid")" 2>/dev/null || true
    fi
    if pid_file_alive shell.pid; then
        kill "$(cat "$STATE_DIR/shell.pid")" 2>/dev/null || true
    fi
    if pid_file_alive launcher.pid; then
        kill "$(cat "$STATE_DIR/launcher.pid")" 2>/dev/null || true
    fi

    sleep 0.3
    rm -f "$STATE_DIR"/*.pid "$STATE_DIR/dbus.env" "$STATE_DIR/loaded.txt"
    echo "sandbox stopped"
}

cmd_status() {
    if sandbox_running; then
        echo "kwin sandbox: running (pid $(cat "$STATE_DIR/kwin.pid"), bus $(bus_address))"
    else
        echo "kwin sandbox: stopped"
    fi

    if pid_file_alive fakenav.pid; then
        echo "fake-nav:     running (pid $(cat "$STATE_DIR/fakenav.pid"))"
    else
        echo "fake-nav:     stopped"
    fi

    if pid_file_alive daemon.pid; then
        echo "daemon:       running (pid $(cat "$STATE_DIR/daemon.pid"))"
    else
        echo "daemon:       stopped"
    fi

    if [ -f "$STATE_DIR/loaded.txt" ] && [ -s "$STATE_DIR/loaded.txt" ]; then
        echo "loaded scripts (best-effort bookkeeping, not queried live):"
        sed 's/^/  - /' "$STATE_DIR/loaded.txt"
    fi
}

cmd_env() {
    require_running
    echo "export DBUS_SESSION_BUS_ADDRESS=\"$(bus_address)\""
}

cmd_qdbus() {
    require_running
    DBUS_SESSION_BUS_ADDRESS="$(bus_address)" qdbus6 "$@"
}

cmd_exec() {
    require_running
    DBUS_SESSION_BUS_ADDRESS="$(bus_address)" "$@"
}

cmd_load() {
    require_running
    local file="${1:?usage: $0 load <qml-file> [pluginName]}"
    local plugin="${2:-$(basename "$file" .qml)}"
    file="$(cd "$(dirname "$file")" && pwd)/$(basename "$file")"

    local id
    id="$(DBUS_SESSION_BUS_ADDRESS="$(bus_address)" qdbus6 org.kde.KWin /Scripting \
        org.kde.kwin.Scripting.loadDeclarativeScript "$file" "$plugin")"
    echo "loadDeclarativeScript($file, $plugin) -> $id"
    echo "$plugin" >> "$STATE_DIR/loaded.txt"

    sleep 0.3
    echo "--- kwin.log tail (check for parse/runtime errors) ---"
    tail -n 15 "$STATE_DIR/kwin.log"
}

cmd_load_js() {
    require_running
    local file="${1:?usage: $0 load-js <js-file> [pluginName]}"
    local plugin="${2:-$(basename "$file" .js)}"
    file="$(cd "$(dirname "$file")" && pwd)/$(basename "$file")"

    local id
    id="$(DBUS_SESSION_BUS_ADDRESS="$(bus_address)" qdbus6 org.kde.KWin /Scripting \
        org.kde.kwin.Scripting.loadScript "$file" "$plugin")"
    echo "loadScript($file, $plugin) -> $id"
    echo "$plugin" >> "$STATE_DIR/loaded.txt"

    sleep 0.3
    echo "--- kwin.log tail (check for parse/runtime errors) ---"
    tail -n 15 "$STATE_DIR/kwin.log"
}

cmd_unload() {
    require_running
    local plugin="${1:?usage: $0 unload <pluginName>}"

    local result
    result="$(DBUS_SESSION_BUS_ADDRESS="$(bus_address)" qdbus6 org.kde.KWin /Scripting \
        org.kde.kwin.Scripting.unloadScript "$plugin")"
    echo "unloadScript($plugin) -> $result"

    if [ -f "$STATE_DIR/loaded.txt" ]; then
        grep -vFx "$plugin" "$STATE_DIR/loaded.txt" > "$STATE_DIR/loaded.txt.tmp" || true
        mv "$STATE_DIR/loaded.txt.tmp" "$STATE_DIR/loaded.txt"
    fi
}

cmd_fake_nav() {
    require_running
    local action="${1:?usage: $0 fake-nav <start|stop> [state.json]}"
    shift

    case "$action" in
        start)
            if pid_file_alive fakenav.pid; then
                echo "fake-nav already running (pid $(cat "$STATE_DIR/fakenav.pid"))" >&2
                exit 1
            fi
            : > "$STATE_DIR/fakenav.log"
            DBUS_SESSION_BUS_ADDRESS="$(bus_address)" \
                nohup "$PYTHON" "$DEV_DIR/fake_navigator.py" "$@" \
                > "$STATE_DIR/fakenav.log" 2>&1 &
            echo $! > "$STATE_DIR/fakenav.pid"
            sleep 0.5
            if ! is_alive "$(cat "$STATE_DIR/fakenav.pid")"; then
                echo "fake-nav failed to start:" >&2
                cat "$STATE_DIR/fakenav.log" >&2
                exit 1
            fi
            echo "fake-nav running (pid $(cat "$STATE_DIR/fakenav.pid"))"
            ;;
        stop)
            if pid_file_alive fakenav.pid; then
                kill "$(cat "$STATE_DIR/fakenav.pid")" 2>/dev/null || true
                rm -f "$STATE_DIR/fakenav.pid"
                echo "fake-nav stopped"
            else
                echo "fake-nav is not running"
            fi
            ;;
        *)
            echo "unknown fake-nav action: $action (expected start|stop)" >&2
            exit 1
            ;;
    esac
}

cmd_daemon() {
    require_running
    local action="${1:?usage: $0 daemon <start|stop>}"

    case "$action" in
        start)
            if pid_file_alive daemon.pid; then
                echo "daemon already running (pid $(cat "$STATE_DIR/daemon.pid"))" >&2
                exit 1
            fi
            echo "note: the daemon's KWinMonitor reads your REAL session's" \
                 "'plasma-kwin_wayland.service' journal (read-only) - focus/caption/closed" \
                 "events will reflect your real desktop, not this sandbox." >&2
            : > "$STATE_DIR/daemon.log"
            ( cd "$REPO_ROOT/backnav-engine" && \
              DBUS_SESSION_BUS_ADDRESS="$(bus_address)" \
                nohup "$PYTHON" backnav.py > "$STATE_DIR/daemon.log" 2>&1 & \
              echo $! > "$STATE_DIR/daemon.pid" )
            sleep 0.5
            if ! is_alive "$(cat "$STATE_DIR/daemon.pid")"; then
                echo "daemon failed to start:" >&2
                cat "$STATE_DIR/daemon.log" >&2
                exit 1
            fi
            echo "daemon running (pid $(cat "$STATE_DIR/daemon.pid"))"
            ;;
        stop)
            if pid_file_alive daemon.pid; then
                kill "$(cat "$STATE_DIR/daemon.pid")" 2>/dev/null || true
                rm -f "$STATE_DIR/daemon.pid"
                echo "daemon stopped"
            else
                echo "daemon is not running"
            fi
            ;;
        *)
            echo "unknown daemon action: $action (expected start|stop)" >&2
            exit 1
            ;;
    esac
}

cmd_logs() {
    local which="${1:-kwin}"
    local follow="${2:-}"
    local file="$STATE_DIR/$which.log"

    if [ ! -f "$file" ]; then
        echo "no log file for '$which' (expected $file)" >&2
        exit 1
    fi

    if [ "$follow" = "-f" ] || [ "$which" = "-f" ]; then
        tail -n 40 -f "$file"
    else
        tail -n 40 "$file"
    fi
}

main() {
    local cmd="${1:-}"
    [ $# -gt 0 ] && shift || true

    case "$cmd" in
        start)    cmd_start "$@" ;;
        stop)     cmd_stop "$@" ;;
        status)   cmd_status "$@" ;;
        env)      cmd_env "$@" ;;
        qdbus)    cmd_qdbus "$@" ;;
        exec)     cmd_exec "$@" ;;
        load)     cmd_load "$@" ;;
        load-js)  cmd_load_js "$@" ;;
        unload)   cmd_unload "$@" ;;
        fake-nav) cmd_fake_nav "$@" ;;
        daemon)   cmd_daemon "$@" ;;
        logs)     cmd_logs "$@" ;;
        *)
            sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 1
            ;;
    esac
}

main "$@"
