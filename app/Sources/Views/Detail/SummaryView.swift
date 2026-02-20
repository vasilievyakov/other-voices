import SwiftUI

struct SummaryView: View {
    let summary: CallSummary
    var templateName: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Summary", systemImage: "sparkles")
                    .font(.title3)
                    .fontWeight(.semibold)
                Spacer()
                templateBadge
            }

            // Change 7: truncation warning banner
            if let warning = summary.truncationWarning {
                Label(warning, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            // Change 8: call title
            if let title = summary.title {
                Text(title)
                    .font(.headline)
            }

            if let text = summary.summary {
                Text(text)
                    .font(.body)
                    .textSelection(.enabled)
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
                            // Change 6: hide decorative icon from accessibility
                            Image(systemName: "arrow.right.circle")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .padding(.top, 3)
                                .accessibilityHidden(true)
                            Text(item)
                                .textSelection(.enabled)
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
                        .textSelection(.enabled)
                }
            }

            // Change 1: additionalSections with AI-generated visual cue
            ForEach(sortedAdditionalKeys, id: \.self) { key in
                if let items = summary.additionalSections[key], !items.isEmpty {
                    additionalBulletSection(key, items: items)
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

    private var sortedAdditionalKeys: [String] {
        summary.additionalSections.keys.sorted()
    }

    @ViewBuilder
    private var templateBadge: some View {
        let name = templateName ?? "default"
        // Change 4: fontWeight(.medium) and opacity 0.2
        // Change 2: replace .cornerRadius(4) with background in: syntax
        Text(name.replacingOccurrences(of: "_", with: " ").capitalized)
            .font(.caption)
            .fontWeight(.medium)
            .padding(.horizontal, 8)
            .padding(.vertical, 2)
            .background(Color.accentColor.opacity(0.2), in: RoundedRectangle(cornerRadius: 4))
    }

    private func bulletSection(_ title: String, items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundStyle(.secondary)

            ForEach(items, id: \.self) { item in
                HStack(alignment: .top, spacing: 6) {
                    // Change 6: hide decorative bullet from accessibility
                    Text("\u{2022}")
                        .foregroundStyle(.secondary)
                        .accessibilityHidden(true)
                    Text(item)
                        .textSelection(.enabled)
                }
                .font(.body)
            }
        }
    }

    // Change 1: separate view builder for additionalSections with secondary header + AI-extracted caption
    private func additionalBulletSection(_ title: String, items: [String]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline)
                    .fontWeight(.semibold)
                    .foregroundStyle(.secondary)
                Text("AI-extracted")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }

            ForEach(items, id: \.self) { item in
                HStack(alignment: .top, spacing: 6) {
                    // Change 6: hide decorative bullet from accessibility
                    Text("\u{2022}")
                        .foregroundStyle(.secondary)
                        .accessibilityHidden(true)
                    Text(item)
                        .textSelection(.enabled)
                }
                .font(.body)
            }
        }
    }

    private func entityChips(_ entities: [Entity]) -> some View {
        FlowLayout(spacing: 6) {
            ForEach(entities) { entity in
                HStack(spacing: 4) {
                    // Change 6: hide decorative entity icons from accessibility
                    Image(systemName: entity.icon)
                        .font(.caption2)
                        .accessibilityHidden(true)
                    Text(entity.name)
                        .font(.caption)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                // Change 3: semantic colors; Change 2: clipShape instead of .cornerRadius
                .background(
                    entity.isPerson
                        ? Color.accentColor.opacity(0.15)
                        : Color.secondary.opacity(0.15)
                )
                .clipShape(RoundedRectangle(cornerRadius: 12))
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
