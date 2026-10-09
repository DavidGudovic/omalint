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

  function widgetLine(widget) {
    return widget.errors + "," + widget.warnings + "," + widget.problems + "|" + widget.summary + "|" + widget.visible
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
    harness.stage = "first-run"
    // Not the 10 s startup timer, which would only make the test slow.
    inst.refresh()
  }

  Component.onCompleted: harness.createService()

  Services.PluginShellApi {
    id: shellApi
    pluginId: harness.pluginId
    barConfig: ({ layout: { right: [{ id: harness.pluginId, refreshIntervalSec: 120 }] } })
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
          + " widgetA=" + harness.widgetLine(widgetA) + " widgetB=" + harness.widgetLine(widgetB))
        harness.stage = "ipc-refresh"
        console.log("HARNESS ready")
      } else if (service.runs === 2) {
        // The service's own startup timer fires at 10 s; the test checks that this came sooner.
        console.log("HARNESS second-run runs=2 afterMs=" + (Date.now() - harness.createdAt))
        Qt.quit()
      }
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
