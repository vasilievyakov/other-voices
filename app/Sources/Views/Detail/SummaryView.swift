import SwiftUI

struct SummaryView: View {
    let summary: CallSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            sectionHeader("Summary")

            if let text = summary.summary {
                Text(text)
                    .font(.body)
            }

            if let points = summary.keyPoints, !points.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Key Points")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)

                    ForEach(points, id: \.self) { point in
                        HStack(alignment: .top, spacing: 6) {
                            Text("\u{2022}")
                                .foregroundStyle(.secondary)
                            Text(point)
                        }
                        .font(.body)
                    }
                }
            }

            if let decisions = summary.decisions, !decisions.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Decisions")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)

                    ForEach(decisions, id: \.self) { decision in
                        HStack(alignment: .top, spacing: 6) {
                            Text("\u{2022}")
                                .foregroundStyle(.secondary)
                            Text(decision)
                        }
                        .font(.body)
                    }
                }
            }

            if let actions = summary.actionItems, !actions.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Action Items")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)

                    ForEach(actions, id: \.self) { item in
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: "square")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .padding(.top, 3)
                            Text(item)
                        }
                        .font(.body)
                    }
                }
            }

            if let participants = summary.participants, !participants.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Participants")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)

                    Text(participants.joined(separator: ", "))
                        .font(.body)
                }
            }
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        HStack {
            Text(title)
                .font(.headline)
                .fontWeight(.bold)
            Spacer()
        }
    }
}
