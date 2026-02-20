import Foundation

struct DaemonStatus: Codable {
    let daemonPid: Int
    let timestamp: String
    let state: String
    let appName: String?
    let sessionId: String?
    let startedAt: String?
    let pipeline: String?

    enum CodingKeys: String, CodingKey {
        case daemonPid = "daemon_pid"
        case timestamp
        case state
        case appName = "app_name"
        case sessionId = "session_id"
        case startedAt = "started_at"
        case pipeline
    }

    var isActive: Bool {
        state != "stopped"
    }

    var isRecording: Bool {
        state == "recording"
    }

    var isProcessing: Bool {
        state == "processing"
    }

    var stateLabel: String {
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

    var recordingDuration: TimeInterval? {
        guard let startedAt, let date = parseDate(startedAt) else { return nil }
        return Date().timeIntervalSince(date)
    }

    private func parseDate(_ string: String) -> Date? {
        Call.iso8601.date(from: string) ?? Call.iso8601Basic.date(from: string)
    }
}
