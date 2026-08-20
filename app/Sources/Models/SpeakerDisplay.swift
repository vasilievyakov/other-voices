import Foundation

/// Display-time substitution of owner-set names for diarization labels.
/// The stored transcript text is never rewritten — names live in the
/// speaker_names table and are applied only when rendering.
package enum SpeakerDisplay {
    /// Name for a label when the owner set one; the label itself otherwise.
    package static func displayName(for label: String, names: [String: String]) -> String {
        if let name = names[label], !name.isEmpty {
            return name
        }
        return label
    }

    /// Replace SPEAKER_* labels in transcript text with owner-set names.
    /// Word-boundary matching keeps SPEAKER_1 from eating into SPEAKER_10.
    package static func substitute(_ text: String, names: [String: String]) -> String {
        guard !names.isEmpty else { return text }
        var result = text
        for (label, name) in names where !name.isEmpty {
            let pattern = "\\b\(NSRegularExpression.escapedPattern(for: label))\\b"
            result = result.replacingOccurrences(
                of: pattern,
                with: NSRegularExpression.escapedTemplate(for: name),
                options: .regularExpression
            )
        }
        return result
    }
}
