import SwiftUI

struct SidebarView: View {
    @Environment(CallStore.self) private var store
    @Environment(DaemonMonitor.self) private var daemon
    @Binding var selection: SidebarItem?

    var body: some View {
        VStack(spacing: 0) {
            List(selection: $selection) {
                librarySection
                appsSection
                peopleSection
            }
            .listStyle(.sidebar)
            .navigationTitle("Other Voices")

            Divider()
            DaemonStatusCard()
                .padding(8)
        }
    }

    // MARK: - Sections

    private var librarySection: some View {
        Section("Library") {
            Label {
                Text("All Calls")
            } icon: {
                Image(systemName: SidebarItem.allCalls.icon)
            }
            .badge(store.totalCount)
            .accessibilityLabel("All Calls, \(store.totalCount) calls")
            .tag(SidebarItem.allCalls)

            Label {
                Text("Action Items")
            } icon: {
                Image(systemName: SidebarItem.actionItems.icon)
            }
            .badge(store.allActionItems().count)
            .accessibilityLabel("Action Items")
            .tag(SidebarItem.actionItems)

            Label {
                Text("Commitments")
            } icon: {
                Image(systemName: SidebarItem.commitments.icon)
            }
            .badge(store.commitmentCounts.outgoing + store.commitmentCounts.incoming)
            .accessibilityLabel("Commitments, \(store.commitmentCounts.outgoing + store.commitmentCounts.incoming) open")
            .tag(SidebarItem.commitments)
        }
    }

    @ViewBuilder
    private var appsSection: some View {
        if !store.appCounts.isEmpty {
            Section("Apps") {
                ForEach(store.appCounts, id: \.0) { appName, count in
                    Label {
                        Text(appName)
                    } icon: {
                        Image(systemName: SidebarItem.app(appName).icon)
                    }
                    .badge(count)
                    .accessibilityLabel("\(appName), \(count) calls")
                    .tag(SidebarItem.app(appName))
                }
            }
        }
    }

    @ViewBuilder
    private var peopleSection: some View {
        if !store.entities.isEmpty {
            Section("People") {
                ForEach(store.entities, id: \.name) { entity in
                    Label {
                        Text(entity.name)
                    } icon: {
                        Image(systemName: entity.icon)
                    }
                    .badge(store.entityCallCount(entity.name) ?? 0)
                    .accessibilityLabel("\(entity.name), \(store.entityCallCount(entity.name) ?? 0) calls")
                    .tag(SidebarItem.entity(entity.name))
                }
            }
        }
    }
}
