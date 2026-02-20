import Foundation
import SQLite3

struct Call: Identifiable, Hashable {
    let sessionId: String
    let appName: String
    let startedAt: Date
    let endedAt: Date
    let durationSeconds: Double
    let systemWavPath: String?
    let micWavPath: String?
    let transcript: String?
    let summaryJson: String?

    var id: String { sessionId }

    var summary: CallSummary? {
        guard let json = summaryJson, let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(CallSummary.self, from: data)
    }

    var durationFormatted: String {
        let total = Int(durationSeconds)
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let seconds = total % 60
        if hours > 0 {
            return String(format: "%dh%02dm%02ds", hours, minutes, seconds)
        }
        return String(format: "%dm%02ds", minutes, seconds)
    }

    var appIcon: String {
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

    static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return f
    }()

    var startedAtFormatted: String {
        Self.dateFormatter.string(from: startedAt)
    }

    static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static let iso8601Basic: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func parseDate(_ string: String) -> Date {
        iso8601.date(from: string)
            ?? iso8601Basic.date(from: string)
            ?? Date()
    }
}
