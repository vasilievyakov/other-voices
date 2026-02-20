import Foundation

struct ActionItem: Identifiable, Hashable {
    let id: String  // sessionId + index
    let text: String
    let sessionId: String
    let appName: String
    let callDate: Date
    let callDateFormatted: String

    var person: String? {
        // Extract @person from text like "задача (@Вася, дедлайн)"
        guard let atRange = text.range(of: "@") else { return nil }
        let afterAt = text[atRange.upperBound...]
        let end = afterAt.firstIndex(where: { $0 == "," || $0 == ")" || $0 == " " }) ?? afterAt.endIndex
        let name = String(afterAt[..<end]).trimmingCharacters(in: .whitespaces)
        return name.isEmpty ? nil : name
    }
}
