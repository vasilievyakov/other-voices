import SwiftUI

struct MainView: View {
    @Environment(CallStore.self) private var store
    @State private var selectedSidebarItem: SidebarItem? = .allCalls
    @State private var selectedCall: Call?
    @State private var searchText = ""

    var body: some View {
        @Bindable var store = store

        NavigationSplitView {
            SidebarView(selection: $selectedSidebarItem)
        } content: {
            if selectedSidebarItem == .actionItems {
                ActionItemsView(selectedCall: $selectedCall)
            } else {
                CallListView(selectedCall: $selectedCall)
                    .searchable(text: $searchText, prompt: "Search calls...")
                    .onChange(of: searchText) { _, newValue in
                        store.setSearch(newValue)
                    }
            }
        } detail: {
            if let call = selectedCall {
                CallDetailView(call: call)
            } else {
                ContentUnavailableView("Select a call", systemImage: "phone.fill",
                    description: Text("Choose a call from the list to see details"))
            }
        }
        .navigationSplitViewStyle(.balanced)
        .onChange(of: selectedSidebarItem) { _, newValue in
            if let item = newValue {
                store.setFilter(item)
                selectedCall = nil
            }
        }
    }
}
