import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "services" as Services
import "plugin" as Plugin

// Mounts the plugin the way the Omarchy shell does: one service, and one bar
// widget per monitor (two here). Every line the test reads starts with HARNESS.
// Nothing in here may call report(): it opens a terminal on the desktop.
ShellRoot {
  id: harness

  readonly property string pluginId: "io.github.davidgudovic.omalint"
  // Assigned once the service exists, so that the widgets' lookups re-evaluate.
  property var service: null
  property string stage: "service-creation"
  property double createdAt: 0
  property double changedAt: 0

  // A new object on every call, as the host hands out a fresh copy of shell.json's bar section.
  function barConfigWith(intervalSec) {
    return { layout: { right: [{ id: harness.pluginId, refreshIntervalSec: intervalSec }] } }
  }

  function widgetLine(widget) {
    return widget.errors + "," + widget.warnings + "," + widget.problems + "|" + widget.summary + "|" + widget.visible
  }

  // The widget's button, found without knowing how the widget lays it out.
  function dimmed(widget) {
    for (var i = 0; i < widget.children.length; i++)
      if ("dimmed" in widget.children[i]) return widget.children[i].dimmed
    return "no-button"
  }

  function createService() {
    var component = Qt.createComponent(Qt.resolvedUrl("plugin/Service.qml"))
    if (component.status !== Component.Ready) {
      console.log("HARNESS service component failed: " + component.errorString())
      return
    }
    var inst = component.createObject(null)
    if (!inst) {
      console.log("HARNESS service createObject returned null: " + component.errorString())
      return
    }
    if ("shell" in inst) inst.shell = shellApi
    if ("manifest" in inst) inst.manifest = { id: harness.pluginId }
    harness.createdAt = Date.now()
    harness.service = inst
    // What the widgets say before anything was checked; runs is still 0 here.
    console.log("HARNESS pending widgetA=" + widgetA.summary + "|" + widgetA.visible
      + " service=" + inst.summary + "|" + inst.checked + " dimmed=" + harness.dimmed(widgetA))
    harness.stage = "first-run"
    // Not the 10 s startup timer, which would only make the test slow.
    inst.refresh()
  }

  Component.onCompleted: harness.createService()

  Services.PluginShellApi {
    id: shellApi
    pluginId: harness.pluginId
    barConfig: harness.barConfigWith(120)
    _serviceLookup: function(id) { return id === harness.pluginId ? harness.service : null }
  }

  PluginBarApi {
    id: barA
    pluginId: harness.pluginId
    moduleName: harness.pluginId
    shell: shellApi
    barForeground: Color.bar.text
    urgent: Color.bar.active
    fontFamily: Style.font.family
    barSize: Style.bar.sizeHorizontal
  }

  PluginBarApi {
    id: barB
    pluginId: harness.pluginId
    moduleName: harness.pluginId
    shell: shellApi
    barForeground: Color.bar.text
    urgent: Color.bar.active
    fontFamily: Style.font.family
    barSize: Style.bar.sizeHorizontal
  }

  FloatingWindow {
    visible: true
    implicitWidth: 200
    implicitHeight: 60

    Row {
      Plugin.Widget {
        id: widgetA
        bar: barA
      }

      Plugin.Widget {
        id: widgetB
        bar: barB
      }
    }
  }

  Connections {
    target: harness.service

    function onRunsChanged() {
      var service = harness.service
      if (service.runs === 1) {
        console.log("HARNESS first-run errors=" + service.errors + " warnings=" + service.warnings
          + " failure=" + service.failure + " runs=" + service.runs
          + " interval=" + service.refreshIntervalSec
          + " widgetA=" + harness.widgetLine(widgetA) + " widgetB=" + harness.widgetLine(widgetB)
          + " dimmed=" + harness.dimmed(widgetA))
        harness.stage = "ipc-refresh"
        console.log("HARNESS ready")
      } else if (service.runs === 2) {
        // The service's own startup timer fires at 10 s; the test checks that this came sooner.
        console.log("HARNESS second-run runs=2 afterMs=" + (Date.now() - harness.createdAt))
        // The same content in a new object: the host does this on every write of shell.json.
        harness.stage = "unchanged-config"
        shellApi.barConfig = harness.barConfigWith(120)
        settle.start()
      } else if (harness.stage === "config-change") {
        // Everything from creation to here takes a few seconds, so neither the startup timer
        // (10 s after creation) nor the repeating one (120 s, then 300 s) can have caused this run;
        // the test adds up the logged times to check that.
        console.log("HARNESS third-run runs=" + service.runs + " interval=" + service.refreshIntervalSec
          + " afterMs=" + (Date.now() - harness.changedAt))
        Qt.quit()
      }
    }
  }

  // Long enough for the service to act on the identical configuration (it waits 1 s), if it wrongly would.
  Timer {
    id: settle
    interval: 2000
    onTriggered: {
      console.log("HARNESS unchanged-config runs=" + harness.service.runs)
      harness.stage = "config-change"
      harness.changedAt = Date.now()
      shellApi.barConfig = harness.barConfigWith(300)
    }
  }

  Timer {
    interval: 25000
    running: true
    onTriggered: {
      console.log("HARNESS deadline stage not reached: " + harness.stage)
      Qt.quit()
    }
  }
}
