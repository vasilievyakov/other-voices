import Foundation

package struct ActionItem: Identifiable, Hashable {
    package let id: String  // sessionId + index
    package let text: String
    package let sessionId: String
    package let appName: String
    package let callDate: Date
    package let callDateFormatted: String

    package var person: String? {
        // Extract @person from text like "задача (@Вася, дедлайн)"
        guard let atRange = text.range(of: "@") else { return nil }
        let afterAt = text[atRange.upperBound...]
        let end = afterAt.firstIndex(where: { $0 == "," || $0 == ")" || $0 == " " }) ?? afterAt.endIndex
        let name = String(afterAt[..<end]).trimmingCharacters(in: .whitespaces)
        return name.isEmpty ? nil : name
    }

    package init(id: String, text: String, sessionId: String, appName: String, callDate: Date, callDateFormatted: String) {
        self.id = id
        self.text = text
        self.sessionId = sessionId
        self.appName = appName
        self.callDate = callDate
        self.callDateFormatted = callDateFormatted
    }
}
