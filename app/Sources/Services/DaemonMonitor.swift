import Foundation

@Observable
final class DaemonMonitor {
    var status: DaemonStatus?
    var isAvailable: Bool { status != nil && status!.isActive }

    private var statusMonitor: StatusMonitor?
    private var durationTimer: Timer?

    // Exposed for live duration display
    var recordingDuration: TimeInterval? {
        status?.recordingDuration
    }

    private let statusPath: String
    private let directoryPath: String

    init() {
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

        // Timer for live duration updates during recording
        durationTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            guard let self, let status = self.status,
                  status.isRecording || status.isProcessing else { return }
            // Trigger observation update by re-reading
            self.readStatus()
        }
    }

    func readStatus() {
        guard let data = FileManager.default.contents(atPath: statusPath) else {
            status = nil
            return
        }
        status = try? JSONDecoder().decode(DaemonStatus.self, from: data)

        // Check if daemon process is actually alive
        if let s = status {
            if !isProcessAlive(pid: s.daemonPid) {
                status = nil
            }
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
