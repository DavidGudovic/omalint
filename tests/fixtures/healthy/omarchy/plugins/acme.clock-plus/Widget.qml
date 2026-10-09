import QtQuick
import "lib/Format.js" as Format

Item {
  implicitWidth: 40
  implicitHeight: 20

  Image {
    // source: "icons/removed.svg"
    source: "icons/clock.svg"
  }

  Loader {
    source: Qt.resolvedUrl("lib/Popup.qml")
  }
}
