import Foundation

package struct Commitment: Identifiable, Hashable {
    package let id: Int
    package let sessionId: String
    package let direction: String  // outgoing, incoming, third_party
    package let whoLabel: String
    package let whoName: String?
    package let toLabel: String?
    package let toName: String?
    package let text: String
    package let verbatimQuote: String?
    package let timestamp: String?
    package let deadlineRaw: String?
    package let deadlineType: String?
    package let significance: String?
    package let uncertain: Bool
    package let status: String  // open, done, dismissed
    package let createdAt: String?
    package let resolvedAt: String?

    // Joined fields from calls table (for cross-call views)
    package let appName: String?
    package let callStartedAt: Date?

    package var isOutgoing: Bool { direction == "outgoing" }
    package var isIncoming: Bool { direction == "incoming" }
    package var isOpen: Bool { status == "open" }

    package var directionIcon: String {
        switch direction {
        case "outgoing": return "arrow.up.circle.fill"
        case "incoming": return "arrow.down.circle.fill"
        default: return "arrow.left.arrow.right.circle"
        }
    }

    package var directionLabel: String {
        switch direction {
        case "outgoing": return "I owe"
        case "incoming": return "Owed to me"
        default: return "Third party"
        }
    }

    package var statusIcon: String {
        switch status {
        case "done": return "checkmark.circle.fill"
        case "dismissed": return "xmark.circle.fill"
        default: return "circle"
        }
    }

    package var displayWho: String {
        whoName ?? whoLabel
    }

    package var displayTo: String {
        toName ?? toLabel ?? ""
    }

    package init(
        id: Int, sessionId: String, direction: String,
        whoLabel: String, whoName: String?, toLabel: String?, toName: String?,
        text: String, verbatimQuote: String?, timestamp: String?,
        deadlineRaw: String?, deadlineType: String?, significance: String?,
        uncertain: Bool, status: String, createdAt: String?, resolvedAt: String?,
        appName: String? = nil, callStartedAt: Date? = nil
    ) {
        self.id = id
        self.sessionId = sessionId
        self.direction = direction
        self.whoLabel = whoLabel
        self.whoName = whoName
        self.toLabel = toLabel
        self.toName = toName
        self.text = text
        self.verbatimQuote = verbatimQuote
        self.timestamp = timestamp
        self.deadlineRaw = deadlineRaw
        self.deadlineType = deadlineType
        self.significance = significance
        self.uncertain = uncertain
        self.status = status
        self.createdAt = createdAt
        self.resolvedAt = resolvedAt
        self.appName = appName
        self.callStartedAt = callStartedAt
    }
}
