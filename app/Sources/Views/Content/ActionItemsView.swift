import SwiftUI

/// Commitments tab — reads the REAL commitments table (extraction v2 with
/// verified quotes), not the legacy action_items strings. Uncertain items
/// live in their own visually distinct section and never mix with the
/// confident debt (Allen's rule: a confident number over shaky data is a lie).
struct ActionItemsView: View {
    @Environment(CallStore.self) private var store
    @Binding var selectedCallId: String?
    @State private var commitments: [Commitment] = []

    private var outgoing: [Commitment] {
        commitments.filter { !$0.uncertain && $0.direction == "outgoing" }
    }
    private var incoming: [Commitment] {
        commitments.filter { !$0.uncertain && $0.direction == "incoming" }
    }
    private var unconfirmed: [Commitment] {
        commitments.filter { $0.uncertain }
    }

    var body: some View {
        List {
            if commitments.isEmpty {
                ContentUnavailableView(
                    "No open commitments",
                    systemImage: "checklist",
                    description: Text(
                        "Not found doesn't mean none were made — extraction "
                        + "doesn't cover everything. New calls feed this list."
                    )
                )
                .listRowSeparator(.hidden)
            } else {
                commitmentSection("You promised", items: outgoing, icon: "arrow.up.right.circle")
                commitmentSection("Promised to you", items: incoming, icon: "arrow.down.left.circle")

                if !unconfirmed.isEmpty {
                    Section {
                        ForEach(unconfirmed) { c in
                            row(c)
                                .opacity(0.6)
                        }
                    } header: {
                        Label("Needs confirmation — low extraction confidence",
                              systemImage: "questionmark.circle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }
        }
        .listStyle(.inset)
        .onAppear { commitments = store.openCommitments() }
        .onChange(of: store.totalCount) { _, _ in
            commitments = store.openCommitments()
        }
    }

    @ViewBuilder
    private func commitmentSection(_ title: String, items: [Commitment], icon: String) -> some View {
        if !items.isEmpty {
            Section {
                ForEach(items) { c in
                    row(c)
                }
            } header: {
                Label(title, systemImage: icon)
                    .font(.caption)
                    .fontWeight(.medium)
            }
        }
    }

    private func row(_ c: Commitment) -> some View {
        Button {
            selectedCallId = c.sessionId
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .top) {
                    Text(c.displayTitle)
                        .font(.body)
                    Spacer()
                    Text(c.callDate)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                // who is COALESCE(who_name, who_label): after the owner renames
                // a speaker this shows the name instead of SPEAKER_N. The
                // owner's own rows (SPEAKER_ME) are already titled by section.
                if !c.who.isEmpty && c.who != "SPEAKER_ME" {
                    Text(c.who)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let due = deadlineLabel(c) {
                    Text("к сроку: \(due)")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
                if let quote = c.quote, !quote.isEmpty {
                    Text("«\(quote)»")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            .padding(.vertical, 2)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens the call for this commitment")
    }

    private func deadlineLabel(_ c: Commitment) -> String? {
        if let date = c.deadlineDate, !date.isEmpty { return date }
        if let deadline = c.deadline, !deadline.isEmpty { return deadline }
        return nil
    }
}
