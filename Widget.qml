import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.davidgudovic.omalint"

  property int errors: 0
  property int warnings: 0
  // Why the last check produced no report; empty when it ran.
  property string failure: ""

  readonly property int problems: errors + warnings
  // `omarchy bar set` stores a string unless it is given --json.
  readonly property bool alwaysShow: String(setting("alwaysShow", false)) === "true"
  readonly property int refreshIntervalSec: Math.max(60, Number(setting("refreshIntervalSec", 1800)) || 1800)
  readonly property string script: decodeURIComponent(String(Qt.resolvedUrl("bin/omalint")).replace(/^file:\/\//, ""))
  readonly property string summary: {
    if (failure) return failure
    if (!problems) return "OmaLint: no problems found"
    var parts = []
    if (errors) parts.push(errors + (errors === 1 ? " error" : " errors"))
    if (warnings) parts.push(warnings + (warnings === 1 ? " warning" : " warnings"))
    return "OmaLint: " + parts.join(", ")
  }

  function refresh() {
    if (!check.running) check.running = true
  }

  // The launcher hands its argument to a second shell, so the path is quoted
  // once for each.
  function report() {
    if (root.bar) root.bar.run("omarchy-launch-floating-terminal-with-presentation "
      + Util.shellQuote(Util.shellQuote(root.script)))
  }

  function apply(text, exitCode) {
    var totals = null
    try { totals = JSON.parse(text).summary } catch (e) {}
    if (!totals || exitCode > 1) {
      failure = "OmaLint could not run (exit status " + exitCode + ")"
      return
    }
    failure = ""
    errors = Number(totals.errors) || 0
    warnings = Number(totals.warnings) || 0
  }

  visible: problems > 0 || failure !== "" || alwaysShow
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  IpcHandler {
    target: "io.github.davidgudovic.omalint"

    function refresh(): void { root.broadcast("refresh") }
    function report(): void { root.report() }
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

  BarIconButton {
    id: button

    readonly property string count: root.problems > 99 ? "99+" : String(root.problems)
    readonly property bool counted: root.problems > 0 && !vertical

    anchors.fill: parent
    bar: root.bar
    text: counted ? count + " " : ""
    slotSize: Style.bar.iconSlot + (counted ? Math.round(Style.bar.iconFont * 0.62 * (count.length + 1)) : 0)
    active: root.errors > 0
    dimmed: root.failure !== ""
    tooltipText: root.summary
    onPressed: function(b) {
      if (b === Qt.RightButton) root.refresh()
      else root.report()
    }
  }
}
