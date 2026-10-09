import QtQuick
import Quickshell.Io
import qs.Commons

// The background check and everything the bar widget shows. The shell mounts
// this once; the bar draws a widget per monitor and an IPC target can only be
// registered once, so the state and the IPC handler live here and the widgets
// only read them.
Item {
  id: root

  // Injected by the host: the plugin's shell facade and its manifest.
  property var shell: null
  property var manifest: null

  readonly property string pluginId: "io.github.davidgudovic.omalint"

  property int errors: 0
  property int warnings: 0
  // Why the last check produced no report; empty when it ran.
  property string failure: ""
  // Finished check runs, whether or not they produced a report.
  property int runs: 0

  // False until the first check has finished: there is nothing to report yet.
  readonly property bool checked: runs > 0
  readonly property int problems: errors + warnings
  readonly property string script: decodeURIComponent(String(Qt.resolvedUrl("bin/omalint")).replace(/^file:\/\//, ""))
  readonly property string summary: {
    if (!checked) return "OmaLint: first check pending"
    if (failure) return failure
    if (!problems) return "OmaLint: no problems found"
    var parts = []
    if (errors) parts.push(errors + (errors === 1 ? " error" : " errors"))
    if (warnings) parts.push(warnings + (warnings === 1 ? " warning" : " warnings"))
    return "OmaLint: " + parts.join(", ")
  }

  // The plugin's own entry in the bar layout, where its settings are kept.
  readonly property var barEntry: {
    var layout = shell && shell.barConfig ? shell.barConfig.layout : null
    if (!layout) return null
    var sections = ["left", "center", "right"]
    for (var s = 0; s < sections.length; s++) {
      var entries = layout[sections[s]]
      if (!Array.isArray(entries)) continue
      for (var i = 0; i < entries.length; i++)
        if (entries[i] && entries[i].id === pluginId) return entries[i]
    }
    return null
  }
  readonly property int refreshIntervalSec: Math.max(60, Number(barEntry ? barEntry.refreshIntervalSec : 0) || 1800)

  function refresh() {
    if (!check.running) check.running = true
  }

  // The bar configuration last seen, as text; empty until the host has injected one.
  property string seenConfig: ""

  // The count would otherwise be stale until the next timed check after the user fixes something.
  // The host reassigns barConfig even when nothing changed, so the content is compared, not the object.
  function noteConfig() {
    var text = shell && shell.barConfig ? JSON.stringify(shell.barConfig) : ""
    if (text === seenConfig) return
    var first = seenConfig === ""
    seenConfig = text
    // The configuration that comes with the injection is the baseline, not a change.
    if (!first) recheck.restart()
  }

  onShellChanged: noteConfig()

  function report() {
    // execArgv passes argv as is and the launcher evaluates its argument once, so the path is quoted once.
    Util.execArgv(["omarchy-launch-floating-terminal-with-presentation", Util.shellQuote(root.script)])
  }

  function apply(text, exitCode) {
    var totals = null
    try { totals = JSON.parse(text).summary } catch (e) {}
    if (!totals || exitCode > 1) {
      failure = "OmaLint could not run (exit status " + exitCode + ")"
    } else {
      failure = ""
      errors = Number(totals.errors) || 0
      warnings = Number(totals.warnings) || 0
    }
    // Last, so that whoever hears of a new run finds its numbers in place.
    runs += 1
  }

  IpcHandler {
    target: root.pluginId

    function refresh(): void { root.refresh() }
    function report(): void { root.report() }
  }

  // The host reassigns barConfig whenever shell.json changes. `shell` is null until it is injected.
  Connections {
    target: root.shell
    function onBarConfigChanged() { root.noteConfig() }
  }

  Timer {
    id: recheck
    interval: 1000
    // A check already under way read the old file; come back when it is done.
    onTriggered: check.running ? recheck.restart() : root.refresh()
  }

  Process {
    id: check
    command: ["/usr/bin/python3", root.script, "--json"]
    stdout: StdioCollector {
      id: output
      waitForEnd: true
    }
    onExited: function(exitCode) { root.apply(output.text, exitCode) }
  }

  // The first check waits for the shell to finish loading its plugins, so a
  // shell that is still starting is not reported as broken.
  Timer {
    interval: 10000
    running: true
    onTriggered: root.refresh()
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }
}
