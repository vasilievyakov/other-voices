import Foundation

struct CallSummary: Codable {
    let summary: String?
    let keyPoints: [String]?
    let decisions: [String]?
    let actionItems: [String]?
    let participants: [String]?

    enum CodingKeys: String, CodingKey {
        case summary
        case keyPoints = "key_points"
        case decisions
        case actionItems = "action_items"
        case participants
    }
}
