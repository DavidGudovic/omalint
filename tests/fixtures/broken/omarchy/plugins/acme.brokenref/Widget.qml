import QtQuick
import "lib/Missing.js" as Missing
// import "lib/Commented.js" as Commented

Item {
  implicitWidth: 20
  implicitHeight: 20

  Image {
    source: Qt.resolvedUrl("icons/gone.svg")
  }

  // A remote image and a runtime path are not local files to verify.
  Image { source: "https://example.com/logo.png" }
  property string label: "source: \"icons/in-a-string.svg\""
}
