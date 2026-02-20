import Foundation

package struct DaemonStatus: Codable, Equatable {
    package let daemonPid: Int
    package let timestamp: String
    package let state: String
    package let appName: String?
    package let sessionId: String?
    package let startedAt: String?
    package let pipeline: String?
    package let ollamaAvailable: Bool?

    enum CodingKeys: String, CodingKey {
        case daemonPid = "daemon_pid"
        case timestamp
        case state
        case appName = "app_name"
        case sessionId = "session_id"
        case startedAt = "started_at"
        case pipeline
        case ollamaAvailable = "ollama_available"
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

    package var isOllamaDown: Bool {
        ollamaAvailable == false
    }

    package var stateLabel: String {
        switch state {
        case "recording": return "Recording"
        case "processing":
            switch pipeline {
            case "transcribing": return "Transcribing"
            case "resolving speakers": return "Resolving Speakers"
            case "summarizing": return "Summarizing"
            case "extracting commitments": return "Extracting Commitments"
            case "saving": return "Saving"
            default: return "Processing"
            }
        case "idle": return "Idle"
        case "stopped": return "Stopped"
        default: return state.capitalized
        }
    }

    // MARK: - User-centric labels

    /// User-friendly description of what the pipeline is doing right now.
    /// Framed around the user's call, not system internals.
    package var pipelineUserLabel: String {
        switch pipeline {
        case "transcribing": return "Transcribing"
        case "resolving speakers": return "Identifying speakers"
        case "summarizing": return "Summarizing"
        case "extracting commitments": return "Extracting action items"
        case "saving": return "Saving"
        default: return "Processing"
        }
    }

    /// Pipeline stages in order, for progress visualization.
    package static let pipelineStages = [
        "transcribing", "resolving speakers", "summarizing",
        "extracting commitments", "saving"
    ]

    /// Fraction (0..1) representing how far through the pipeline we are.
    package var pipelineProgress: Double {
        guard let pipeline else { return 0 }
        let stages = Self.pipelineStages
        guard let idx = stages.firstIndex(of: pipeline) else { return 0 }
        return Double(idx + 1) / Double(stages.count)
    }

    package var recordingDuration: TimeInterval? {
        guard let startedAt, let date = parseDate(startedAt) else { return nil }
        return Date().timeIntervalSince(date)
    }

    private func parseDate(_ string: String) -> Date? {
        Call.iso8601.date(from: string) ?? Call.iso8601Basic.date(from: string)
    }
}
