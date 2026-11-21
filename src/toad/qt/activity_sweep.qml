import QtQuick

Item {
    id: root
    property bool running: false
    property color primary: "transparent"
    property color accent: "transparent"
    property color secondary: "transparent"
    property real minimumWidth: 0.32
    property real maximumWidth: 0.64
    property int travelDuration: 3200
    property int breathingDuration: 2700

    Rectangle {
        id: band
        visible: root.running
        height: root.height / 2
        y: (root.height - height) / 2
        width: root.width * root.minimumWidth
        x: -width
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: root.primary }
            GradientStop { position: 0.5; color: root.accent }
            GradientStop { position: 1.0; color: root.secondary }
        }

        NumberAnimation on x {
            from: -band.width
            to: root.width
            duration: root.travelDuration
            loops: Animation.Infinite
            running: root.running
        }
        SequentialAnimation on width {
            loops: Animation.Infinite
            running: root.running
            NumberAnimation {
                from: root.width * root.minimumWidth
                to: root.width * root.maximumWidth
                duration: root.breathingDuration / 2
            }
            NumberAnimation {
                from: root.width * root.maximumWidth
                to: root.width * root.minimumWidth
                duration: root.breathingDuration / 2
            }
        }
    }
}
