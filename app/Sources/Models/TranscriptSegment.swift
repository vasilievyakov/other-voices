import Foundation

package struct TranscriptSegment: Codable, Identifiable, Hashable {
    package let start: Double
    package let end: Double
    package let text: String

    package var id: Double { start }

    package var startFormatted: String {
        Self.formatTime(start)
    }

    package var endFormatted: String {
        Self.formatTime(end)
    }

    package var rangeFormatted: String {
        "\(startFormatted)-\(endFormatted)"
    }

    package init(start: Double, end: Double, text: String) {
        self.start = start
        self.end = end
        self.text = text
    }

    static func formatTime(_ seconds: Double) -> String {
        let total = Int(seconds)
        let m = total / 60
        let s = total % 60
        return String(format: "%d:%02d", m, s)
    }
}
