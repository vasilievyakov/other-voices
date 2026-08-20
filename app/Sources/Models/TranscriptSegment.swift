import Foundation

package struct TranscriptSegment: Codable, Identifiable, Hashable {
    package let start: Double
    package let end: Double
    package let text: String
    /// Diarization label (SPEAKER_ME / SPEAKER_1 / SPEAKER_OTHER); nil for
    /// segments stored before speaker separation existed.
    package let speaker: String?

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

    package init(start: Double, end: Double, text: String, speaker: String? = nil) {
        self.start = start
        self.end = end
        self.text = text
        self.speaker = speaker
    }

    static func formatTime(_ seconds: Double) -> String {
        let total = Int(seconds)
        let m = total / 60
        let s = total % 60
        return String(format: "%d:%02d", m, s)
    }
}
