import SwiftUI

package struct MainView: View {
    package init() {}
    @Environment(CallStore.self) private var store
    @State private var selectedSidebarItem: SidebarItem? = .allCalls
    @State private var selectedCallId: String?
    @State private var searchText = ""

    package var body: some View {
        @Bindable var store = store

        NavigationSplitView {
            SidebarView(selection: $selectedSidebarItem)
        } content: {
            switch selectedSidebarItem {
            case .actionItems:
                ActionItemsView(selectedCallId: $selectedCallId)
            case .commitments:
                CommitmentsView(selectedCallId: $selectedCallId)
            default:
                CallListView(selectedCallId: $selectedCallId)
            }
        } detail: {
            if let sessionId = selectedCallId {
                CallDetailView(sessionId: sessionId)
            } else {
                ContentUnavailableView("Select a call", systemImage: "phone.fill",
                    description: Text("Choose a call from the list to see details"))
            }
        }
        .searchable(text: $searchText, prompt: "Search calls...")
        .onChange(of: searchText) { _, newValue in
            store.setSearch(newValue)
        }
        .navigationSplitViewStyle(.balanced)
        .onChange(of: selectedSidebarItem) { _, newValue in
            if let item = newValue {
                store.setFilter(item)
                selectedCallId = nil
            }
        }
    }
}
