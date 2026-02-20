import Foundation

@Observable
package final class DaemonMonitor {
    package var status: DaemonStatus?
    package var isAvailable: Bool { status != nil && status!.isActive }

    private var statusMonitor: StatusMonitor?
    private var durationTimer: Timer?

    // Exposed for live duration display
    var recordingDuration: TimeInterval? {
        status?.recordingDuration
    }

    private let statusPath: String
    private let directoryPath: String

    package init() {
        let dataDir = NSHomeDirectory() + "/call-recorder/data"
        self.statusPath = dataDir + "/status.json"
        self.directoryPath = dataDir
        startMonitoring()
    }

    func startMonitoring() {
        // Initial read
        readStatus()

        // Watch directory for changes
        statusMonitor = StatusMonitor(directoryPath: directoryPath) { [weak self] in
            self?.readStatus()
        }
        statusMonitor?.start()

        // Timer for live duration display during recording only
        durationTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self, let s = self.status, s.isRecording else { return }
            // Force @Observable update for recordingDuration (computed from current time)
            self.readStatus()
        }
    }

    func readStatus() {
        guard let data = FileManager.default.contents(atPath: statusPath) else {
            if status != nil { status = nil }
            return
        }
        let newStatus = try? JSONDecoder().decode(DaemonStatus.self, from: data)

        // Check if daemon process is actually alive
        let resolved: DaemonStatus?
        if let s = newStatus, isProcessAlive(pid: s.daemonPid) {
            resolved = s
        } else {
            resolved = nil
        }

        // Only update if changed — prevents @Observable from triggering spurious SwiftUI re-renders
        if resolved != status {
            status = resolved
        }
    }

    private func isProcessAlive(pid: Int) -> Bool {
        kill(Int32(pid), 0) == 0
    }

    deinit {
        statusMonitor?.stop()
        durationTimer?.invalidate()
    }
}
