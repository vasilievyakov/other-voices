import SwiftUI

struct ActionItemsView: View {
    @Environment(CallStore.self) private var store
    @Binding var selectedCall: Call?
    @State private var items: [ActionItem] = []

    var body: some View {
        List {
            if items.isEmpty {
                ContentUnavailableView("No action items",
                    systemImage: "checklist",
                    description: Text("Action items from your calls will appear here"))
                .listRowSeparator(.hidden)
            } else {
                ForEach(groupedByCall, id: \.0) { sessionId, callItems in
                    Section {
                        ForEach(callItems) { item in
                            ActionItemRow(item: item)
                                .onTapGesture {
                                    selectedCall = store.getCall(item.sessionId).flatMap { $0 }
                                }
                        }
                    } header: {
                        if let first = callItems.first {
                            HStack {
                                Image(systemName: iconForApp(first.appName))
                                    .foregroundStyle(.secondary)
                                Text(first.appName)
                                    .fontWeight(.medium)
                                Text("—")
                                    .foregroundStyle(.tertiary)
                                Text(first.callDateFormatted)
                                    .foregroundStyle(.secondary)
                            }
                            .font(.caption)
                        }
                    }
                }
            }
        }
        .listStyle(.inset)
        .onAppear { items = store.allActionItems() }
        .onChange(of: store.totalCount) { _, _ in items = store.allActionItems() }
    }

    private var groupedByCall: [(String, [ActionItem])] {
        var dict: [String: [ActionItem]] = [:]
        var order: [String] = []
        for item in items {
            if dict[item.sessionId] == nil {
                order.append(item.sessionId)
            }
            dict[item.sessionId, default: []].append(item)
        }
        return order.map { ($0, dict[$0]!) }
    }

    private func iconForApp(_ name: String) -> String {
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

struct ActionItemRow: View {
    let item: ActionItem

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "square")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 2) {
                Text(item.text)
                    .font(.body)

                if let person = item.person {
                    Text(person)
                        .font(.caption)
                        .foregroundStyle(.tint)
                }
            }
        }
        .padding(.vertical, 2)
        .contentShape(Rectangle())
    }
}
