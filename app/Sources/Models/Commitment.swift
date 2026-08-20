import Foundation

/// One row of the commitments table — a promise extracted from a call,
/// verified against the transcript, owned by its status lifecycle
/// (only the owner closes; the LLM never touches status).
package struct Commitment: Identifiable, Hashable {
    package let id: Int
    package let sessionId: String
    package let direction: String  // outgoing | incoming | third_party
    package let who: String
    package let text: String
    package let quote: String?
    package let deadline: String?
    package let uncertain: Bool
    package let appName: String
    package let callDate: String

    package init(
        id: Int,
        sessionId: String,
        direction: String,
        who: String,
        text: String,
        quote: String?,
        deadline: String?,
        uncertain: Bool,
        appName: String,
        callDate: String
    ) {
        self.id = id
        self.sessionId = sessionId
        self.direction = direction
        self.who = who
        self.text = text
        self.quote = quote
        self.deadline = deadline
        self.uncertain = uncertain
        self.appName = appName
        self.callDate = callDate
    }

    package var isOutgoing: Bool { direction == "outgoing" }
}
