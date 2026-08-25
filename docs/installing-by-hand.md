# Installing by hand

Part of [BackNav](../README.md).

Everything [`install.sh`](../install.sh) does, in the order it does
it, for anyone who would rather run the steps themselves or wants to
know what it touched. The script is the shorter path and this page is
the same job; neither is more correct.

The browser extensions and the per-application settings are NOT here -
the script does not do those either, and they are in the README where
everyone needs them.

Start with the tools and the daemon's two dependencies:

```bash
sudo apt install git python3-websockets python3-dbus-next
```

Installing them from apt rather than pip is not a preference. Ubuntu
24.04 and later ship Python as an externally managed environment, so
`pip install` into the system refuses outright and tells you to use the
package manager - which has both, so there is nothing to work around.

```bash
git clone https://github.com/davidmal1/backnav.git
cd backnav
kpackagetool6 --type KWin/Script -i backnav-kwin
kpackagetool6 --type KWin/Script -i backnav-kwin-overlay
```

The `cd` matters, and skipping it fails badly: `kpackagetool6` takes the
two names as relative paths, so from anywhere else you get

```
Error: Installation of  failed: No such file:
```

which names neither what it wanted nor where it looked - and it exits 0
while doing it. If you see that, you are in the wrong directory.

Enable both scripts in **System Settings → Window Management → KWin
Scripts**.

Bind *BackNav: Navigate Back* under **Shortcuts → KWin**. Assign your
desired shortcut key. That one shortcut is the whole interface.

There is a second action, *BackNav: Navigate Forward*, which is entirely
optional - see [Navigate Forward is
optional](../README.md#navigate-forward-is-optional). Leaving it
unbound costs nothing.

Then set the daemon up to run with your session. Its dependencies came
from the `apt` line above, so there is nothing further to install.

The directory will not exist yet on a machine that has never had a user
service, which is most of them:

```bash
mkdir -p ~/.config/systemd/user
```

Put this in `~/.config/systemd/user/backnav.service`, replacing both
copies of `/home/you/backnav` with where you cloned it. It has to be
written out in full - systemd does not expand `~`, so the `~/backnav`
used elsewhere on this page will not work here:

```ini
[Unit]
Description=BackNav navigation daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 /home/you/backnav/backnav-engine/backnav.py
WorkingDirectory=/home/you/backnav/backnav-engine
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
```

Save the file, then enter these in a terminal to load and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now backnav
```

To watch what it is seeing - this one follows the log and keeps the
terminal until you press Ctrl+C:

```bash
journalctl --user -u backnav -f
```

`daemon-reload` is there because the directory is new: systemd scans for
unit files when it starts, and one appearing in a path that did not exist
then is not noticed on its own. If the unit reports as **masked**, the
file is empty - systemd treats a zero-byte unit the same as a deliberately
masked one, and says so in wording that suggests neither.

`/usr/bin/python3` is correct only if the dependencies came from apt as
above. If you used a virtualenv instead, `ExecStart` has to name that
interpreter - `/path/to/venv/bin/python3` - because systemd runs the unit
without your shell, so an activated venv is not inherited. The failure is
a clean `ModuleNotFoundError` in the journal.

You can also run it directly, which is worth knowing for debugging
because it prints to the terminal instead of the journal - but it holds
that terminal for as long as it runs, and it will not start while the
service has the ports:

```bash
python3 backnav-engine/backnav.py
```
