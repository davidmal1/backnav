//
// Modifier-survival probe for the kwin-sandbox.
//
// Established so far, on real keys inside the nested sandbox:
//   - typing reaches a Konsole running inside it  -> input traverses fine
//   - a BARE F12 global shortcut FIRES            -> nested KWin really
//     does dispatch global shortcuts
//   - Ctrl+Alt+Shift+B / +N / +P never fire       -> something about the
//     modified combos specifically does not match
//
// That last point is not a curiosity, it is blocking: the whole question
// the sandbox exists to answer (does globalShortcutReleased fire per
// key-tap or per whole-combo release?) is inherently about a HELD
// MODIFIER. If no modifier survives the nesting, the sandbox can never
// answer it and the test has to move to the real session.
//
// So this registers one action per modifier combination to find which,
// if any, get through. Function keys throughout, deliberately: Shift
// changes the KEYSYM of a letter key (Shift+b -> "B") but leaves F-keys
// alone, so using letters would confound "modifier lost" with "keysym
// resolved differently".
//
// All fresh action names - an action with an existing kglobalshortcutsrc
// entry ignores whatever default registerShortcut() passes.
//
// Load with:
//   dev/kwin-sandbox.sh load-js dev/probe_shortcut.js backnav-probe
//
const PROBES = [
    ["BackNavProbeBare",     "F12"],
    ["BackNavProbeShift",    "Shift+F8"],
    // Ctrl+F5 rather than any lower Ctrl+F-key: KWin claims Ctrl+F1..F4
    // for "Switch to Desktop N" and Ctrl+F7/F9/F10 for the Expose family,
    // in the sandbox exactly as in the real session (the sandbox inherits
    // KWin's built-in defaults). A probe on a combo KWin already owns is
    // silently never bound.
    ["BackNavProbeCtrl5",    "Ctrl+F5"],
    ["BackNavProbeAlt",      "Alt+F10"],
    ["BackNavProbeMeta",     "Meta+F11"],
    ["BackNavProbeCtrlAlt",  "Ctrl+Alt+F7"],
    ["BackNavProbeTriple",   "Ctrl+Alt+Shift+F6"],
];

for (const [name, key] of PROBES) {
    registerShortcut(name, "BackNav probe: " + key, key, (function(label) {
        return function() {
            console.log("BACKNAV-PROBE-HIT: " + label + " at " + Date.now());
        };
    })(key));
}

console.log("BACKNAV-PROBE: registered " + PROBES.length + " probes: " +
            PROBES.map(function(p) { return p[1]; }).join(", "));
