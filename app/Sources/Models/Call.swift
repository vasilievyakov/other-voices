import Foundation
import SQLite3

package struct Call: Identifiable, Hashable {
    package let sessionId: String
    package let appName: String
    package let startedAt: Date
    package let endedAt: Date
    package let durationSeconds: Double
    package let systemWavPath: String?
    package let micWavPath: String?
    package let transcript: String?
    package let summaryJson: String?

    package var id: String { sessionId }

    package var summary: CallSummary? {
        guard let json = summaryJson, let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(CallSummary.self, from: data)
    }

    package var durationFormatted: String {
        let total = Int(durationSeconds)
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let seconds = total % 60
        if hours > 0 {
            return String(format: "%dh%02dm%02ds", hours, minutes, seconds)
        }
        return String(format: "%dm%02ds", minutes, seconds)
    }

    package var appIcon: String {
        switch appName {
        case "Zoom": return "video.fill"
        case "Google Meet": return "globe"
        case "Telegram": return "bubble.left.fill"
        case "FaceTime": return "phone.fill"
        case "Discord": return "headphones"
        case "Microsoft Teams": return "person.3.fill"
        default: return "phone.fill"
        }
    }

    package static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return f
    }()

    package var startedAtFormatted: String {
        Self.dateFormatter.string(from: startedAt)
    }

    package static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    package static let iso8601Basic: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    package static func parseDate(_ string: String) -> Date {
        iso8601.date(from: string)
            ?? iso8601Basic.date(from: string)
            ?? Date()
    }

    package init(
        sessionId: String, appName: String, startedAt: Date, endedAt: Date,
        durationSeconds: Double, systemWavPath: String?, micWavPath: String?,
        transcript: String?, summaryJson: String?
    ) {
        self.sessionId = sessionId
        self.appName = appName
        self.startedAt = startedAt
        self.endedAt = endedAt
        self.durationSeconds = durationSeconds
        self.systemWavPath = systemWavPath
        self.micWavPath = micWavPath
        self.transcript = transcript
        self.summaryJson = summaryJson
    }
}
