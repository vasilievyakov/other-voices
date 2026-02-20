import Foundation

@MainActor
@Observable
package final class DaemonMonitor {
    package var status: DaemonStatus?
    package var isAvailable: Bool { status != nil && status!.isActive }
    package var ollamaAvailable: Bool = true  // Assume available until proven otherwise

    private var statusMonitor: StatusMonitor?
    private var durationTimer: Timer?
    private var ollamaTimer: Timer?

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
            MainActor.assumeIsolated {
                self?.readStatus()
            }
        }
        statusMonitor?.start()

        // Timer for live duration display during recording only
        durationTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, let s = self.status, s.isRecording else { return }
                // Force @Observable update for recordingDuration (computed from current time)
                self.readStatus()
            }
        }

        // Check Ollama availability every 30 seconds (only when daemon is active)
        checkOllamaAvailability()
        ollamaTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.checkOllamaAvailability()
            }
        }
    }

    func stopMonitoring() {
        statusMonitor?.stop()
        statusMonitor = nil
        durationTimer?.invalidate()
        durationTimer = nil
        ollamaTimer?.invalidate()
        ollamaTimer = nil
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

        // Prefer daemon's Ollama status (from status.json) when daemon is alive
        if let s = resolved, let daemonOllama = s.ollamaAvailable {
            if ollamaAvailable != daemonOllama {
                ollamaAvailable = daemonOllama
            }
        }
    }

    private nonisolated func isProcessAlive(pid: Int) -> Bool {
        kill(Int32(pid), 0) == 0
    }

    /// Ping Ollama API to check availability using async URLSession.
    private func checkOllamaAvailability() {
        guard let url = URL(string: "http://localhost:11434/api/tags") else {
            ollamaAvailable = false
            return
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3

        Task { [weak self] in
            let available: Bool
            do {
                let (_, response) = try await URLSession.shared.data(for: request)
                if let http = response as? HTTPURLResponse {
                    available = http.statusCode == 200
                } else {
                    available = false
                }
            } catch {
                available = false
            }
            if self?.ollamaAvailable != available {
                self?.ollamaAvailable = available
            }
        }
    }
}
