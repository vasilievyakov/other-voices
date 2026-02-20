import Foundation

package enum SidebarItem: Hashable {
    case allCalls
    case actionItems
    case app(String)

    package var label: String {
        switch self {
        case .allCalls: return "All Calls"
        case .actionItems: return "Action Items"
        case .app(let name): return name
        }
    }

    package var icon: String {
        switch self {
        case .allCalls: return "phone.fill"
        case .actionItems: return "checklist"
        case .app(let name):
            switch name {
            case "Zoom": return "video.fill"
            case "Google Meet": return "globe"
            case "Telegram": return "bubble.left.fill"
            case "FaceTime": return "phone.fill"
            case "Discord": return "headphones"
            case "Microsoft Teams": return "person.3.fill"
            default: return "phone.fill"
            }
        }
    }
}
