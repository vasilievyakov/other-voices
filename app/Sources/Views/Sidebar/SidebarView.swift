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
                Text("Commitments")
            } icon: {
                Image(systemName: SidebarItem.actionItems.icon)
            }
            .badge(store.allActionItems().count)
            .accessibilityLabel("Commitments")
            .tag(SidebarItem.actionItems)

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

    // The People section shows people. Tools, configs and gadgets extracted as
    // entities («iMac», «Kensington Lock») made half the list unusable for the
    // person-briefing flow (board cycle 3, Ive).
    private var people: [Entity] {
        store.entities.filter { $0.type == "person" }
    }

    @ViewBuilder
    private var peopleSection: some View {
        if !people.isEmpty {
            Section("People") {
                ForEach(people, id: \.name) { entity in
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
