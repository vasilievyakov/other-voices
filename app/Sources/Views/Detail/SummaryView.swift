import SwiftUI

struct SummaryView: View {
    let summary: CallSummary
    var templateName: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Summary")
                    .font(.headline)
                    .fontWeight(.bold)
                Spacer()
                if let tmpl = templateName, tmpl != "default" {
                    Text(tmpl.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.caption)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(Color.accentColor.opacity(0.15))
                        .cornerRadius(4)
                }
            }

            if let text = summary.summary {
                Text(text)
                    .font(.body)
            }

            if let points = summary.keyPoints, !points.isEmpty {
                bulletSection("Key Points", items: points)
            }

            if let decisions = summary.decisions, !decisions.isEmpty {
                bulletSection("Decisions", items: decisions)
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

            // Entities
            if let entities = summary.entities, !entities.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("People & Companies")
                        .font(.subheadline)
                        .fontWeight(.semibold)
                        .foregroundStyle(.secondary)

                    let people = entities.filter { $0.isPerson }
                    let companies = entities.filter { $0.isCompany }

                    if !people.isEmpty {
                        entityChips(people)
                    }
                    if !companies.isEmpty {
                        entityChips(companies)
                    }
                }
            }
        }
    }

    private func bulletSection(_ title: String, items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundStyle(.secondary)

            ForEach(items, id: \.self) { item in
                HStack(alignment: .top, spacing: 6) {
                    Text("\u{2022}")
                        .foregroundStyle(.secondary)
                    Text(item)
                }
                .font(.body)
            }
        }
    }

    private func entityChips(_ entities: [Entity]) -> some View {
        FlowLayout(spacing: 6) {
            ForEach(entities) { entity in
                HStack(spacing: 4) {
                    Image(systemName: entity.icon)
                        .font(.caption2)
                    Text(entity.name)
                        .font(.caption)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(entity.isPerson ? Color.blue.opacity(0.1) : Color.orange.opacity(0.1))
                .cornerRadius(12)
            }
        }
    }
}

// Simple flow layout for chips
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = layout(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = layout(proposal: proposal, subviews: subviews)
        for (index, position) in result.positions.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + position.x, y: bounds.minY + position.y), proposal: .unspecified)
        }
    }

    private func layout(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, positions: [CGPoint]) {
        let maxWidth = proposal.width ?? .infinity
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
        }

        return (CGSize(width: maxWidth, height: y + rowHeight), positions)
    }
}
