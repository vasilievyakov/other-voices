import Foundation

package struct Entity: Codable, Hashable, Identifiable {
    package let name: String
    package let type: String

    package var id: String { "\(type):\(name)" }

    package var isPerson: Bool { type == "person" }
    package var isCompany: Bool { type == "company" }

    package var icon: String {
        isPerson ? "person.fill" : "building.2.fill"
    }

    package init(name: String, type: String) {
        self.name = name
        self.type = type
    }
}
