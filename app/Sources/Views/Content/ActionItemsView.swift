import SwiftUI

struct ActionItemsView: View {
    @Environment(CallStore.self) private var store
    @Binding var selectedCallId: String?
    @State private var items: [ActionItem] = []

    var body: some View {
        List {
            if items.isEmpty {
                ContentUnavailableView("No action items",
                    systemImage: "checklist",
                    description: Text("Complete a call to see action items here."))
                .listRowSeparator(.hidden)
            } else {
                ForEach(groupedByCall, id: \.0) { sessionId, callItems in
                    Section {
                        ForEach(callItems) { item in
                            Button {
                                selectedCallId = item.sessionId
                            } label: {
                                ActionItemRow(item: item)
                            }
                            .buttonStyle(.plain)
                            .accessibilityHint("Opens the call for this action item")
                        }
                    } header: {
                        if let first = callItems.first {
                            HStack {
                                // TODO: use Call.iconForApp(name) once a static method is added to Call.swift
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

    // TODO: remove this once Call.swift exposes a static iconForApp(_:) method;
    // then replace all call sites with Call.iconForApp(name).
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
            Image(systemName: "arrow.right.circle")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .padding(.top, 2)
                .accessibilityHidden(true)

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
