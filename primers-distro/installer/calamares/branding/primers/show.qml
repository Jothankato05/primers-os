/* PRIMERS OS — installer slideshow (Calamares slideshow API 2, Qt 5) */
import QtQuick 2.0
import calamares.slideshow 1.0

Presentation {
    id: presentation

    function nextSlide() { presentation.goToNextSlide(); }

    Timer {
        id: advanceTimer
        interval: 7000
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: nextSlide()
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#12161C"
            Image {
                id: logo1
                source: "mark-dark.png"
                width: 96; height: 96
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: parent.height * 0.18
            }
            Text {
                id: title1
                anchors.top: logo1.bottom; anchors.topMargin: 24
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#F5F2EA"; font.pixelSize: 26; font.bold: true
                text: "Welcome to PRIMERS OS"
            }
            Text {
                anchors.top: title1.bottom; anchors.topMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#B9BEC6"; font.pixelSize: 16
                text: "An AI-native desktop built on Ubuntu 22.04 LTS. Lightweight, fast, and ready for work, study and play."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#12161C"
            Image {
                id: logo2
                source: "mark-dark.png"
                width: 96; height: 96
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: parent.height * 0.18
            }
            Text {
                id: title2
                anchors.top: logo2.bottom; anchors.topMargin: 24
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#F5F2EA"; font.pixelSize: 26; font.bold: true
                text: "Meet the PRIMERS Brain"
            }
            Text {
                anchors.top: title2.bottom; anchors.topMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#B9BEC6"; font.pixelSize: 16
                text: "Press Super+Enter any time. Ask it 'how is my system?', 'am I safe?' or 'any advice?' It watches your system, explains what it finds and learns how you work."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#12161C"
            Image {
                id: logo3
                source: "mark-dark.png"
                width: 96; height: 96
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: parent.height * 0.18
            }
            Text {
                id: title3
                anchors.top: logo3.bottom; anchors.topMargin: 24
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#F5F2EA"; font.pixelSize: 26; font.bold: true
                text: "Windows apps and games"
            }
            Text {
                anchors.top: title3.bottom; anchors.topMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#B9BEC6"; font.pixelSize: 16
                text: "Double-click any .exe to run it with Wine. Lutris, GameMode, MangoHud and Vulkan drivers are already set up."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#12161C"
            Image {
                id: logo4
                source: "mark-dark.png"
                width: 96; height: 96
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: parent.height * 0.18
            }
            Text {
                id: title4
                anchors.top: logo4.bottom; anchors.topMargin: 24
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#F5F2EA"; font.pixelSize: 26; font.bold: true
                text: "Secure by default"
            }
            Text {
                anchors.top: title4.bottom; anchors.topMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#B9BEC6"; font.pixelSize: 16
                text: "Firewall on, CPU mitigations on, automatic security updates, and a defensive security engine watching processes and network connections. Add software any time with 'primers-install'."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#0a1a27"
            Image {
                id: logoBee
                source: "lite-bee.png"
                width: 96; height: 96
                fillMode: Image.PreserveAspectFit
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: parent.height * 0.18
            }
            Text {
                id: titleBee
                anchors.top: logoBee.bottom; anchors.topMargin: 24
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#e6ad39"; font.pixelSize: 26; font.bold: true
                text: "Primers Lite Bee"
            }
            Text {
                anchors.top: titleBee.bottom; anchors.topMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width * 0.8
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#f4efe6"; font.pixelSize: 16
                text: "Our own browser, built for speed. It sees whether you are on Wi-Fi, LTE or 2G and loads only what your connection can afford. It blocks ads and trackers, shows a live data meter and saves pages for offline reading."
            }
        }
    }

    function onActivate() { presentation.currentSlide = 0; }
    function onLeave() { }
}
