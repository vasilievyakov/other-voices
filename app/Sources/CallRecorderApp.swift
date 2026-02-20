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
    }
}
