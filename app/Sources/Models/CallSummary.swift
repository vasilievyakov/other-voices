import Foundation
import OSLog

private let logger = Logger(subsystem: "com.user.other-voices", category: "summary")

package struct CallSummary: Hashable {
    package let summary: String?
    package let keyPoints: [String]?
    package let decisions: [String]?
    package let actionItems: [String]?
    package let participants: [String]?
    package let entities: [Entity]?
    package let additionalSections: [String: [String]]
    package var title: String?
    package var truncationWarning: String?

    package init(
        summary: String? = nil,
        keyPoints: [String]? = nil,
        decisions: [String]? = nil,
        actionItems: [String]? = nil,
        participants: [String]? = nil,
        entities: [Entity]? = nil,
        additionalSections: [String: [String]] = [:],
        title: String? = nil,
        truncationWarning: String? = nil
    ) {
        self.summary = summary
        self.keyPoints = keyPoints
        self.decisions = decisions
        self.actionItems = actionItems
        self.participants = participants
        self.entities = entities
        self.additionalSections = additionalSections
        self.title = title
        self.truncationWarning = truncationWarning
    }

    /// Known top-level keys that have dedicated fields
    private static let knownKeys: Set<String> = [
        "summary", "key_points", "decisions", "action_items",
        "participants", "entities", "template",
        "title", "truncation_warning"
    ]

    /// Decode from JSON data with extensive fallback logic.
    /// Always uses dict-based path to capture additional/unknown sections.
    package static func decode(from data: Data) -> CallSummary? {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return decodeFromDict(json)
    }

    /// Decode from a raw JSON dictionary, handling all known format variations
    private static func decodeFromDict(_ json: [String: Any]) -> CallSummary {
        var summaryText: String? = nil
        var keyPoints: [String]? = nil
        var decisions: [String]? = nil
        var actionItems: [String]? = nil
        var participants: [String]? = nil
        var entities: [Entity]? = nil
        var additional: [String: [String]] = [:]
        var title: String? = nil
        var truncationWarning: String? = nil

        // 1. Handle "summary" field — can be string or dict
        if let s = json["summary"] as? String {
            summaryText = s
        } else if let dict = json["summary"] as? [String: Any] {
            // summary is a nested dict — extract text from known subkeys
            if let nested = dict["summary"] as? String {
                summaryText = nested
            } else if let nested = dict["text"] as? String {
                summaryText = nested
            } else if let topic = dict["topic"] as? String {
                summaryText = topic
            }

            // Also extract list fields from within the nested dict
            let nestedResult = extractListFields(from: dict, knownKeys: knownKeys)
            keyPoints = nestedResult.keyPoints ?? keyPoints
            decisions = nestedResult.decisions ?? decisions
            actionItems = nestedResult.actionItems ?? actionItems
            participants = nestedResult.participants ?? participants

            // Merge additional sections from nested dict
            for (k, v) in nestedResult.additional {
                additional[k] = v
            }
        }

        // 2. Extract standard list fields from top level
        let topLevel = extractListFields(from: json, knownKeys: knownKeys)
        keyPoints = keyPoints ?? topLevel.keyPoints
        decisions = decisions ?? topLevel.decisions
        actionItems = actionItems ?? topLevel.actionItems
        participants = participants ?? topLevel.participants

        // 3. Title and truncation warning
        if let t = json["title"] as? String { title = t }
        if let w = json["truncation_warning"] as? String { truncationWarning = w }

        // 4. Entities
        if let entitiesArr = json["entities"] as? [[String: Any]] {
            entities = entitiesArr.compactMap { dict in
                guard let name = dict["name"] as? String,
                      let type = dict["type"] as? String else { return nil }
                return Entity(name: name, type: type)
            }
        }

        // 5. Merge top-level additional sections
        for (k, v) in topLevel.additional {
            if additional[k] == nil { additional[k] = v }
        }

        return CallSummary(
            summary: summaryText,
            keyPoints: keyPoints,
            decisions: decisions,
            actionItems: actionItems,
            participants: participants,
            entities: entities,
            additionalSections: additional,
            title: title,
            truncationWarning: truncationWarning
        )
    }

    /// Result of extracting list fields from a JSON dict
    private struct ExtractedFields {
        var keyPoints: [String]?
        var decisions: [String]?
        var actionItems: [String]?
        var participants: [String]?
        var additional: [String: [String]] = [:]
    }

    /// Extract string-list fields from a JSON dict
    private static func extractListFields(from dict: [String: Any], knownKeys: Set<String>) -> ExtractedFields {
        var result = ExtractedFields()

        for (key, value) in dict {
            // Extract string arrays
            if let arr = value as? [String] {
                switch key {
                case "key_points": result.keyPoints = arr
                case "decisions": result.decisions = arr
                case "action_items": result.actionItems = arr
                case "participants": result.participants = arr
                default:
                    if !knownKeys.contains(key) && !arr.isEmpty {
                        result.additional[formatSectionTitle(key)] = arr
                    }
                }
            }
            // Handle arrays of dicts (e.g. main_topics: [{topic: "", details: [""]}])
            else if let arr = value as? [[String: Any]], !arr.isEmpty, !knownKeys.contains(key) {
                let strings = arr.compactMap { item -> String? in
                    if let topic = item["topic"] as? String {
                        if let details = item["details"] as? [String], !details.isEmpty {
                            return "\(topic): \(details.joined(separator: "; "))"
                        }
                        return topic
                    }
                    if let name = item["name"] as? String { return name }
                    if let text = item["text"] as? String { return text }
                    return nil
                }
                if !strings.isEmpty {
                    result.additional[formatSectionTitle(key)] = strings
                }
            }
            // Handle scalar string values for unknown keys — wrap as single-element array
            else if let str = value as? String, !knownKeys.contains(key), !str.isEmpty {
                result.additional[formatSectionTitle(key)] = [str]
            }
            // Handle numeric and bool scalars for unknown keys — convert to String and wrap
            else if let num = value as? NSNumber, !knownKeys.contains(key) {
                // Bool is bridged as NSNumber in ObjC; check objCType to distinguish
                let str: String
                if String(cString: num.objCType) == "c" {
                    str = num.boolValue ? "true" : "false"
                } else {
                    str = num.stringValue
                }
                if !str.isEmpty {
                    result.additional[formatSectionTitle(key)] = [str]
                }
            }
        }

        return result
    }

    /// Convert snake_case key to Title Case section header
    private static func formatSectionTitle(_ key: String) -> String {
        key.replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }
}

// MARK: - Standard Codable wrapper for first-pass decoding
private struct CodableCallSummary: Codable {
    let summary: String?
    let keyPoints: [String]?
    let decisions: [String]?
    let actionItems: [String]?
    let participants: [String]?
    let entities: [Entity]?

    enum CodingKeys: String, CodingKey {
        case summary
        case keyPoints = "key_points"
        case decisions
        case actionItems = "action_items"
        case participants
        case entities
    }

    func toCallSummary() -> CallSummary {
        CallSummary(
            summary: summary,
            keyPoints: keyPoints,
            decisions: decisions,
            actionItems: actionItems,
            participants: participants,
            entities: entities
        )
    }
}
