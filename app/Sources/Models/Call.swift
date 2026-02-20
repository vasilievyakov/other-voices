import Foundation
import SQLite3

package struct Call: Identifiable {
    package let sessionId: String
    package let appName: String
    package let startedAt: Date
    package let endedAt: Date
    package let durationSeconds: Double
    package let systemWavPath: String?
    package let micWavPath: String?
    package let transcript: String?
    package let summaryJson: String?
    package let templateName: String?
    package let notes: String?
    package let transcriptSegmentsJson: String?
    package let summary: CallSummary?

    package var id: String { sessionId }

    /// Raw summary text for fallback display when decode partially fails
    package var rawSummaryText: String? {
        guard summaryJson != nil else { return nil }
        if summary == nil { return summaryJson }
        return nil
    }

    package var transcriptSegments: [TranscriptSegment]? {
        guard let json = transcriptSegmentsJson, let data = json.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode([TranscriptSegment].self, from: data)
    }

    package var callTitle: String? {
        // First try the dedicated title field
        if let title = summary?.title, !title.isEmpty {
            return title
        }
        // Fallback: first sentence of summary text
        if let text = summary?.summary, !text.isEmpty {
            let firstSentence = text.prefix(while: { $0 != "." && $0 != "\n" })
            let trimmed = String(firstSentence).trimmingCharacters(in: .whitespaces)
            return trimmed.isEmpty ? nil : String(trimmed.prefix(80))
        }
        return nil
    }

    package var durationFormatted: String {
        let total = Int(durationSeconds)
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let seconds = total % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, seconds)
        }
        return String(format: "%d:%02d", minutes, seconds)
    }

    package static func iconForApp(_ name: String) -> String {
        switch name {
        case "Zoom": return "video.fill"
        case "Google Meet": return "globe"
        case "Telegram": return "bubble.left.fill"
        case "FaceTime": return "phone.fill"
        case "Discord": return "headphones"
        case "Microsoft Teams": return "person.3.fill"
        default: return "phone.fill"
        }
    }

    package var appIcon: String {
        Call.iconForApp(appName)
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
        transcript: String?, summaryJson: String?,
        templateName: String? = "default", notes: String? = nil,
        transcriptSegmentsJson: String? = nil,
        summary: CallSummary? = nil
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
        self.templateName = templateName
        self.notes = notes
        self.transcriptSegmentsJson = transcriptSegmentsJson
        // Pre-parse summary if provided; otherwise parse from summaryJson
        if let summary {
            self.summary = summary
        } else if let json = summaryJson, let data = json.data(using: .utf8) {
            self.summary = CallSummary.decode(from: data)
        } else {
            self.summary = nil
        }
    }
}

// MARK: - Hashable (by sessionId only, avoids hashing transcript/summary)

extension Call: Hashable {
    package static func == (lhs: Call, rhs: Call) -> Bool {
        lhs.sessionId == rhs.sessionId
    }

    package func hash(into hasher: inout Hasher) {
        hasher.combine(sessionId)
    }
}
