import Foundation

package struct Template: Codable, Identifiable, Hashable {
    package let name: String
    package let displayName: String
    package let description: String

    package var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name
        case displayName = "display_name"
        case description
    }

    package init(name: String, displayName: String, description: String) {
        self.name = name
        self.displayName = displayName
        self.description = description
    }

    package static func loadFromJSON() -> [Template] {
        let path = NSHomeDirectory() + "/call-recorder/data/templates.json"
        guard let data = FileManager.default.contents(atPath: path) else { return defaultTemplates }
        return (try? JSONDecoder().decode([Template].self, from: data)) ?? defaultTemplates
    }

    package static let defaultTemplates: [Template] = [
        Template(name: "default", displayName: "Default", description: "Standard summary"),
        Template(name: "sales_call", displayName: "Sales Call", description: "Sales-focused"),
        Template(name: "one_on_one", displayName: "1-on-1", description: "One-on-one meeting"),
        Template(name: "standup", displayName: "Standup", description: "Daily standup"),
        Template(name: "interview", displayName: "Interview", description: "Interview debrief"),
        Template(name: "brainstorm", displayName: "Brainstorm", description: "Brainstorming session"),
    ]
}
