import Foundation

package struct CallSummary: Codable {
    package let summary: String?
    package let keyPoints: [String]?
    package let decisions: [String]?
    package let actionItems: [String]?
    package let participants: [String]?

    enum CodingKeys: String, CodingKey {
        case summary
        case keyPoints = "key_points"
        case decisions
        case actionItems = "action_items"
        case participants
    }
}
