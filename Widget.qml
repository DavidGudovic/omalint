import QtQuick
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.davidgudovic.omalint"

  // Null under a replacement bar, after a load error and while the plugin is
  // being disabled. The state and the IPC handler live in Service.qml, because
  // the bar draws this widget once per monitor.
  readonly property var service: (bar && bar.shell && typeof bar.shell.serviceFor === "function")
    ? (bar.shell.serviceFor(root.moduleName) || null) : null

  readonly property int errors: service ? service.errors : 0
  readonly property int warnings: service ? service.warnings : 0
  readonly property string failure: service ? service.failure : "OmaLint: its background service is not loaded"
  readonly property int problems: errors + warnings
  readonly property string summary: service ? service.summary : failure
  // `omarchy bar set` stores a string unless it is given --json.
  readonly property bool alwaysShow: String(setting("alwaysShow", false)) === "true"

  visible: problems > 0 || failure !== "" || alwaysShow
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // Room for the count, measured in the bar's font rather than guessed.
  TextMetrics {
    id: countMetrics
    font.family: button.fontFamily
    font.pixelSize: button.fontSize
    text: button.count + " "
  }

  BarIconButton {
    id: button

    readonly property string glyph: "\uf0ae"
    readonly property string count: root.problems > 99 ? "99+" : String(root.problems)
    readonly property bool counted: root.problems > 0 && !vertical

    anchors.fill: parent
    bar: root.bar
    text: counted ? count + " " + glyph : glyph
    slotSize: Style.bar.iconSlot + (counted ? Math.ceil(countMetrics.advanceWidth) : 0)
    active: root.errors > 0
    dimmed: root.failure !== ""
    tooltipText: root.summary
    onPressed: function(b) {
      if (!root.service) return
      if (b === Qt.RightButton) root.service.refresh()
      else root.service.report()
    }
  }
}
