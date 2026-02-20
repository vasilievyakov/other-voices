import Foundation

package struct ChatMessage: Identifiable, Hashable {
    package let id: String
    package let role: String
    package let content: String
    package let createdAt: String?

    package var isUser: Bool { role == "user" }
    package var isAssistant: Bool { role == "assistant" }

    package init(id: String = UUID().uuidString, role: String, content: String, createdAt: String? = nil) {
        self.id = id
        self.role = role
        self.content = content
        self.createdAt = createdAt
    }
}
