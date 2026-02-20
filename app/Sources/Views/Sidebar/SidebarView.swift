import SwiftUI

struct SidebarView: View {
    @Environment(CallStore.self) private var store
    @Environment(DaemonMonitor.self) private var daemon
    @Binding var selection: SidebarItem?

    var body: some View {
        List(selection: $selection) {
            DaemonStatusCard()
                .listRowSeparator(.hidden)
                .listRowInsets(EdgeInsets(top: 8, leading: 8, bottom: 8, trailing: 8))

            Section("Library") {
                Label {
                    HStack {
                        Text("All Calls")
                        Spacer()
                        Text("\(store.totalCount)")
                            .foregroundStyle(.secondary)
                            .font(.caption)
                    }
                } icon: {
                    Image(systemName: "phone.fill")
                }
                .tag(SidebarItem.allCalls)

                Label {
                    HStack {
                        Text("Action Items")
                        Spacer()
                        let count = store.allActionItems().count
                        if count > 0 {
                            Text("\(count)")
                                .foregroundStyle(.secondary)
                                .font(.caption)
                        }
                    }
                } icon: {
                    Image(systemName: "checklist")
                }
                .tag(SidebarItem.actionItems)
            }

            if !store.appCounts.isEmpty {
                Section("Apps") {
                    ForEach(store.appCounts, id: \.0) { appName, count in
                        Label {
                            HStack {
                                Text(appName)
                                Spacer()
                                Text("\(count)")
                                    .foregroundStyle(.secondary)
                                    .font(.caption)
                            }
                        } icon: {
                            Image(systemName: iconForApp(appName))
                        }
                        .tag(SidebarItem.app(appName))
                    }
                }
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("Other Voices")
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
