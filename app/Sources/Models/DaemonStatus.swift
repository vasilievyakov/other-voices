import Foundation

package struct DaemonStatus: Codable {
    package let daemonPid: Int
    package let timestamp: String
    package let state: String
    package let appName: String?
    package let sessionId: String?
    package let startedAt: String?
    package let pipeline: String?

    enum CodingKeys: String, CodingKey {
        case daemonPid = "daemon_pid"
        case timestamp
        case state
        case appName = "app_name"
        case sessionId = "session_id"
        case startedAt = "started_at"
        case pipeline
    }

    package var isActive: Bool {
        state != "stopped"
    }

    package var isRecording: Bool {
        state == "recording"
    }

    package var isProcessing: Bool {
        state == "processing"
    }

    package var stateLabel: String {
        switch state {
        case "recording": return "Recording"
        case "processing":
            switch pipeline {
            case "transcribing": return "Transcribing"
            case "summarizing": return "Summarizing"
            case "saving": return "Saving"
            default: return "Processing"
            }
        case "idle": return "Idle"
        case "stopped": return "Stopped"
        default: return state.capitalized
        }
    }

    package var recordingDuration: TimeInterval? {
        guard let startedAt, let date = parseDate(startedAt) else { return nil }
        return Date().timeIntervalSince(date)
    }

    private func parseDate(_ string: String) -> Date? {
        Call.iso8601.date(from: string) ?? Call.iso8601Basic.date(from: string)
    }
}
