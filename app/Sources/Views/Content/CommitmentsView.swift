import SwiftUI

struct CommitmentsView: View {
    @Binding var selectedCallId: String?
    @Environment(CallStore.self) private var store
    @State private var filter: CommitmentFilter = .all

    enum CommitmentFilter: String, CaseIterable {
        case all = "All"
        case outgoing = "I Owe"
        case incoming = "Owed to Me"
    }

    private var commitments: [Commitment] {
        switch filter {
        case .all: return store.getOpenCommitments()
        case .outgoing: return store.getOpenCommitments(direction: "outgoing")
        case .incoming: return store.getOpenCommitments(direction: "incoming")
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Filter picker
            Picker("Filter", selection: $filter) {
                ForEach(CommitmentFilter.allCases, id: \.self) { f in
                    Text(f.rawValue).tag(f)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)

            Divider()

            if commitments.isEmpty {
                ContentUnavailableView(
                    "No Open Commitments",
                    systemImage: "checkmark.circle",
                    description: Text("Commitments from your calls will appear here.")
                )
            } else {
                List(commitments) { commitment in
                    CommitmentRowView(commitment: commitment) {
                        store.updateCommitmentStatus(id: commitment.id, status: "done")
                    } onDismiss: {
                        store.updateCommitmentStatus(id: commitment.id, status: "dismissed")
                    } onNavigate: {
                        selectedCallId = commitment.sessionId
                    }
                }
                .listStyle(.inset)
            }
        }
        .navigationTitle("Commitments")
    }
}

// MARK: - Row

private struct CommitmentRowView: View {
    let commitment: Commitment
    let onComplete: () -> Void
    let onDismiss: () -> Void
    let onNavigate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: commitment.directionIcon)
                    .foregroundStyle(commitment.isOutgoing ? .orange : .blue)
                    .accessibilityLabel(commitment.directionLabel)

                Text(commitment.directionLabel)
                    .font(.caption)
                    .fontWeight(.medium)
                    .foregroundStyle(commitment.isOutgoing ? .orange : .blue)

                Spacer()

                if let deadline = commitment.deadlineRaw {
                    Label(deadline, systemImage: "calendar")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Text(commitment.text)
                .font(.body)
                .lineLimit(3)

            if let quote = commitment.verbatimQuote, !quote.isEmpty {
                Text("\"\(quote)\"")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .italic()
                    .lineLimit(2)
            }

            HStack(spacing: 8) {
                if let appName = commitment.appName {
                    Label(appName, systemImage: Call.iconForApp(appName))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                if let date = commitment.callStartedAt {
                    Text(Call.dateFormatter.string(from: date))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }

                Spacer()

                Button("Done", systemImage: "checkmark.circle") { onComplete() }
                    .buttonStyle(.borderless)
                    .font(.caption)
                    .foregroundStyle(.green)
                    .help("Mark as done")

                Button("Dismiss", systemImage: "xmark.circle") { onDismiss() }
                    .buttonStyle(.borderless)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .help("Dismiss this commitment")

                Button("Go to call", systemImage: "arrow.right.circle") { onNavigate() }
                    .buttonStyle(.borderless)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .help("Open the call where this commitment was made")
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}
