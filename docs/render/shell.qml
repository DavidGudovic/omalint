import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "services" as Services
import "plugin" as Plugin

// Renders the README images offscreen. The plugin is mounted as the Omarchy shell
// mounts it: Service.qml runs the real CLI, Widget.qml reads the result from the
// service. Nothing here tells the widget what to show. Never call report() on the
// service: it opens a terminal on the desktop.
ShellRoot {
  id: renderer

  readonly property string pluginId: "io.github.davidgudovic.omalint"
  readonly property string outDir: Quickshell.env("RENDER_OUT")

  // report.json is the CLI's own text report, split into styled segments by docs/render/segments.py.
  readonly property var report: parseReport(reportFile.text())
  // The terminal colors come from the theme, as they do in Omarchy's terminals.
  readonly property var palette: parsePalette(themeFile.text())
  property var service: null
  property string stage: "creating the service"

  function parseReport(text) {
    try { return JSON.parse(text) } catch (e) { return { lines: [], errors: -1, warnings: -1 } }
  }

  function parsePalette(text) {
    var found = {}
    var rows = text.split("\n")
    for (var i = 0; i < rows.length; i++) {
      var match = rows[i].match(/^(\w+)\s*=\s*"(#[0-9a-fA-F]{6})"/)
      if (match) found[match[1]] = match[2]
    }
    return found
  }

  function tone(style) {
    if (style === "red") return palette.red
    if (style === "green") return palette.green
    if (style === "yellow") return palette.yellow
    if (style === "dim") return palette.dark_foreground
    if (style === "bold") return palette.bright_foreground
    return palette.foreground
  }

  function fail(message) {
    console.log("RENDER failed: " + message)
    Qt.exit(1)
  }

  function createService() {
    var component = Qt.createComponent(Qt.resolvedUrl("plugin/Service.qml"))
    var inst = component.status === Component.Ready ? component.createObject(null) : null
    if (!inst) return fail("service: " + component.errorString())
    inst.shell = shellApi
    inst.manifest = { id: renderer.pluginId }
    renderer.service = inst
    renderer.stage = "waiting for the first check"
    // Not the service's 10 s startup timer, which would only make this slow.
    inst.refresh()
  }

  // Saves the item as a PNG at the given scale, then calls next.
  function grab(item, file, scale, next) {
    renderer.stage = "saving " + file
    var started = item.grabToImage(function(result) {
      if (!result.saveToFile(renderer.outDir + "/" + file)) return renderer.fail("could not save " + file)
      console.log("RENDER saved " + file + " " + Math.round(item.width * scale) + "x" + Math.round(item.height * scale))
      next()
    }, Qt.size(item.width * scale, item.height * scale))
    if (!started) fail("could not grab " + file)
  }

  function capture() {
    var s = renderer.service
    console.log("RENDER service errors=" + s.errors + " warnings=" + s.warnings + " failure=" + s.failure)
    if (s.failure !== "") return fail("the service could not run the check")
    if (!report.lines.length) return fail("report.json is missing or empty")
    // Two readings of the same run, through different paths; they must agree.
    if (s.errors !== report.errors || s.warnings !== report.warnings)
      return fail("the report says " + report.errors + " errors and " + report.warnings + " warnings")
    grab(card, "report.png", 2, function() {
      grab(closeup, "widget.png", 4, function() {
        grab(canvas, "preview.png", 2, function() { Qt.exit(0) })
      })
    })
  }

  Component.onCompleted: createService()

  FileView {
    id: reportFile
    path: Quickshell.shellPath("report.json")
    blockLoading: true
  }

  FileView {
    id: themeFile
    path: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme/colors.toml"
    blockLoading: true
  }

  Services.PluginShellApi {
    id: shellApi
    pluginId: renderer.pluginId
    _serviceLookup: function(id) { return id === renderer.pluginId ? renderer.service : null }
  }

  PluginBarApi {
    id: api
    pluginId: renderer.pluginId
    moduleName: renderer.pluginId
    shell: shellApi
    barForeground: Color.bar.text
    urgent: Color.bar.active
    fontFamily: Style.font.family
    barSize: Style.bar.sizeHorizontal
  }

  FloatingWindow {
    visible: true
    implicitWidth: canvas.width
    implicitHeight: closeup.y + closeup.height
    color: Color.background

    // The marketplace image: a strip of bar with the widget on it, above the report.
    Rectangle {
      id: canvas
      width: card.width + 28
      height: card.y + card.height + 14
      color: renderer.palette.darker_background

      Rectangle {
        width: parent.width
        height: Style.bar.sizeHorizontal
        color: Color.bar.background

        Plugin.Widget {
          anchors.right: parent.right
          anchors.rightMargin: 10
          anchors.verticalCenter: parent.verticalCenter
          bar: api
        }
      }

      // The terminal that a click on the widget opens.
      Rectangle {
        id: card
        x: 14
        y: Style.bar.sizeHorizontal + 14
        width: lines.implicitWidth + 28
        height: lines.implicitHeight + 28
        color: renderer.palette.background
        border.width: 1
        border.color: renderer.palette.selection
        radius: Style.cornerRadius

        Column {
          id: lines
          x: 14
          y: 14
          Repeater {
            model: renderer.report.lines
            Row {
              required property var modelData
              height: 15
              Repeater {
                model: modelData
                Text {
                  required property var modelData
                  textFormat: Text.PlainText
                  text: modelData[1]
                  color: renderer.tone(modelData[0])
                  font.family: Style.font.family
                  font.pixelSize: 12
                  font.bold: modelData[0] === "bold"
                }
              }
              // Keeps an empty line as tall as the others.
              Text { text: " "; font.family: Style.font.family; font.pixelSize: 12 }
            }
          }
        }
      }
    }

    // The README close-up: the bar's end, widget right-aligned.
    Rectangle {
      id: closeup
      y: canvas.height + 20
      width: 260
      height: Style.bar.sizeHorizontal + 12
      color: Color.bar.background

      Plugin.Widget {
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        bar: api
      }
    }
  }

  // The first check has finished once the service counts a run. Give the widget's
  // bindings and layout a moment to follow before taking pictures.
  Connections {
    target: renderer.service

    function onRunsChanged() {
      if (renderer.service.runs === 1) settle.start()
    }
  }

  Timer {
    id: settle
    interval: 500
    onTriggered: renderer.capture()
  }

  Timer {
    interval: 30000
    running: true
    onTriggered: {
      console.log("RENDER deadline: not reached: " + renderer.stage)
      Qt.exit(1)
    }
  }
}
