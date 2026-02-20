import SwiftUI

struct CallListView: View {
    @Environment(CallStore.self) private var store
    @Binding var selectedCall: Call?

    var body: some View {
        List(store.calls, selection: $selectedCall) { call in
            CallRowView(call: call)
                .tag(call)
        }
        .listStyle(.inset)
        .overlay {
            if store.calls.isEmpty {
                if store.searchQuery.isEmpty {
                    ContentUnavailableView("No calls yet",
                        systemImage: "phone.badge.plus",
                        description: Text("Recorded calls will appear here"))
                } else {
                    ContentUnavailableView.search(text: store.searchQuery)
                }
            }
        }
    }
}
