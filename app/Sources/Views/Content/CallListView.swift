import SwiftUI

struct CallListView: View {
    @Environment(CallStore.self) private var store
    @Binding var selectedCallId: String?

    var body: some View {
        List(selection: $selectedCallId) {
            ForEach(groupedCalls, id: \.0) { label, calls in
                Section(label) {
                    ForEach(calls) { call in
                        CallRowView(call: call)
                            .tag(call.sessionId)
                    }
                }
            }
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

    private var groupedCalls: [(String, [Call])] {
        let calendar = Calendar.current
        let now = Date()

        var groups: [(String, [Call])] = []
        var current: (String, [Call])?

        for call in store.calls {
            let label = dateGroupLabel(for: call.startedAt, now: now, calendar: calendar)
            if current?.0 == label {
                current?.1.append(call)
            } else {
                if let existing = current {
                    groups.append(existing)
                }
                current = (label, [call])
            }
        }
        if let existing = current {
            groups.append(existing)
        }
        return groups
    }

    private static let monthYearFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MMMM yyyy"
        return f
    }()

    private func dateGroupLabel(for date: Date, now: Date, calendar: Calendar) -> String {
        if calendar.isDateInToday(date) {
            return "Today"
        } else if calendar.isDateInYesterday(date) {
            return "Yesterday"
        } else if calendar.isDate(date, equalTo: now, toGranularity: .weekOfYear) {
            return "This Week"
        } else {
            return Self.monthYearFormatter.string(from: date)
        }
    }
}
