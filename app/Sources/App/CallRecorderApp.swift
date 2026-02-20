import OtherVoicesLib
import SwiftUI

@main
struct OtherVoicesApp: App {
    @State private var callStore = CallStore()
    @State private var daemonMonitor = DaemonMonitor()

    var body: some Scene {
        WindowGroup {
            MainView()
                .environment(callStore)
                .environment(daemonMonitor)
        }
        .defaultSize(width: 1100, height: 700)
        .commands {
            CommandGroup(after: .textEditing) {
                Button("Play / Pause") {
                    NotificationCenter.default.post(name: .togglePlayback, object: nil)
                }
                .keyboardShortcut(.space, modifiers: [.option])
            }
        }

        Settings {
            SettingsView()
        }

        MenuBarExtra("Other Voices", systemImage: "waveform.circle") {
            if let status = daemonMonitor.status {
                Text("Status: \(status.stateLabel)")
                if let app = status.appName {
                    Text("App: \(app)")
                }
                Divider()
            } else {
                Text("Daemon Offline")
                Divider()
            }
            Button("Open Other Voices") {
                NSApplication.shared.activate(ignoringOtherApps: true)
            }
            .keyboardShortcut("o")
        }
        .menuBarExtraStyle(.menu)
    }
}

// Notification.Name.togglePlayback is defined in OtherVoicesLib
