import SwiftUI

struct PersonDetailView: View {
    let personName: String
    @Binding var selectedCallId: String?
    @Environment(CallStore.self) private var store

    private var calls: [Call] { store.callsByEntity(name: personName) }
    private var commitments: [Commitment] { store.commitmentsByPerson(name: personName) }
    private var stats: SQLiteDatabase.PersonStats { store.personStats(name: personName) }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                headerSection
                Divider().padding(.horizontal, 16)
                communicationPatternsSection
                Divider().padding(.horizontal, 16)
                timelineSection
                if !commitments.isEmpty {
                    Divider().padding(.horizontal, 16)
                    commitmentsSection
                }
                keyTopicsSection
            }
        }
        .navigationTitle(personName)
    }

    // MARK: - Header

    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(.blue.opacity(0.12))
                        .frame(width: 56, height: 56)
                    Text(initials(for: personName))
                        .font(.title2)
                        .fontWeight(.semibold)
                        .foregroundStyle(.blue)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(personName)
                        .font(.title2)
                        .fontWeight(.bold)

                    HStack(spacing: 16) {
                        Label("\(stats.totalCalls) calls", systemImage: "phone.fill")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)

                        if stats.totalDuration > 0 {
                            Label(formatTotalDuration(stats.totalDuration),
                                  systemImage: "clock.fill")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                Spacer()
            }

            if let first = stats.firstCallDate, let last = stats.lastCallDate {
                HStack(spacing: 16) {
                    Label {
                        Text("First: \(Call.dateFormatter.string(from: first))")
                    } icon: {
                        Image(systemName: "calendar")
                    }
                    .font(.caption)
                    .foregroundStyle(.secondary)

                    if first != last {
                        Label {
                            Text("Last: \(Call.dateFormatter.string(from: last))")
                        } icon: {
                            Image(systemName: "calendar.badge.clock")
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(16)
    }

    // MARK: - Communication Patterns

    private var communicationPatternsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Communication")
                .font(.headline)
                .padding(.bottom, 2)

            let currentStats = stats

            // Frequency
            if let first = currentStats.firstCallDate, let last = currentStats.lastCallDate {
                let daySpan = max(1, Calendar.current.dateComponents([.day], from: first, to: last).day ?? 1)
                let weekSpan = max(1, Double(daySpan) / 7.0)
                let monthSpan = max(1, Double(daySpan) / 30.0)
                let perWeek = Double(currentStats.totalCalls) / weekSpan
                let perMonth = Double(currentStats.totalCalls) / monthSpan

                HStack(spacing: 24) {
                    StatCard(
                        value: String(format: "%.1f", perWeek),
                        label: "per week",
                        icon: "calendar.day.timeline.left"
                    )
                    StatCard(
                        value: String(format: "%.1f", perMonth),
                        label: "per month",
                        icon: "calendar"
                    )
                    if currentStats.totalCalls > 0 {
                        StatCard(
                            value: formatDuration(currentStats.totalDuration / Double(currentStats.totalCalls)),
                            label: "avg duration",
                            icon: "timer"
                        )
                    }
                }
            }

            // App breakdown
            if !currentStats.appBreakdown.isEmpty {
                HStack(spacing: 12) {
                    ForEach(currentStats.appBreakdown, id: \.0) { appName, count in
                        HStack(spacing: 4) {
                            Image(systemName: Call.iconForApp(appName))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text("\(appName)")
                                .font(.caption)
                            Text("\(count)")
                                .font(.caption)
                                .fontWeight(.semibold)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
                    }
                }
            }

            // Recency indicator
            if let last = currentStats.lastCallDate {
                let daysAgo = Calendar.current.dateComponents([.day], from: last, to: Date()).day ?? 0
                HStack(spacing: 6) {
                    Circle()
                        .fill(recencyColor(daysAgo: daysAgo))
                        .frame(width: 8, height: 8)
                    Text(recencyLabel(daysAgo: daysAgo))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(16)
    }

    // MARK: - Call Timeline

    private var timelineSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Call Timeline")
                .font(.headline)
                .padding(.bottom, 2)

            let callsList = calls
            if callsList.isEmpty {
                Text("No calls recorded")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .padding(.vertical, 8)
            } else {
                ForEach(callsList) { call in
                    Button {
                        selectedCallId = call.sessionId
                    } label: {
                        TimelineRowView(call: call)
                    }
                    .buttonStyle(.plain)

                    if call.sessionId != callsList.last?.sessionId {
                        Divider().padding(.leading, 36)
                    }
                }
            }
        }
        .padding(16)
    }

    // MARK: - Commitments

    private var commitmentsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            let allCommitments = commitments
            let openCount = allCommitments.filter { $0.isOpen }.count
            let doneCount = allCommitments.filter { $0.status == "done" }.count
            let dismissedCount = allCommitments.filter { $0.status == "dismissed" }.count

            HStack {
                Text("Commitments")
                    .font(.headline)
                Spacer()
                if openCount > 0 {
                    Text("\(openCount) open")
                        .font(.caption)
                        .fontWeight(.medium)
                        .foregroundStyle(.orange)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(.orange.opacity(0.12), in: Capsule())
                }
                if doneCount > 0 {
                    Text("\(doneCount) done")
                        .font(.caption)
                        .foregroundStyle(.green)
                }
                if dismissedCount > 0 {
                    Text("\(dismissedCount) dismissed")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            // Open commitments first
            let open = allCommitments.filter { $0.isOpen }
            if !open.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Open")
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .foregroundStyle(.orange)

                    ForEach(open) { commitment in
                        PersonCommitmentRow(commitment: commitment) {
                            store.updateCommitmentStatus(id: commitment.id, status: "done")
                        } onDismiss: {
                            store.updateCommitmentStatus(id: commitment.id, status: "dismissed")
                        } onNavigate: {
                            selectedCallId = commitment.sessionId
                        }
                    }
                }
            }

            // Completed
            let done = allCommitments.filter { $0.status == "done" }
            if !done.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Completed")
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .foregroundStyle(.green)

                    ForEach(done) { commitment in
                        PersonCommitmentRow(commitment: commitment, onNavigate: {
                            selectedCallId = commitment.sessionId
                        })
                    }
                }
            }

            // Dismissed
            let dismissed = allCommitments.filter { $0.status == "dismissed" }
            if !dismissed.isEmpty {
                DisclosureGroup {
                    ForEach(dismissed) { commitment in
                        PersonCommitmentRow(commitment: commitment, onNavigate: {
                            selectedCallId = commitment.sessionId
                        })
                    }
                } label: {
                    Text("Dismissed (\(dismissed.count))")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(16)
    }

    // MARK: - Key Topics

    @ViewBuilder
    private var keyTopicsSection: some View {
        let topics = extractTopics(from: calls)
        if !topics.isEmpty {
            Divider().padding(.horizontal, 16)
            VStack(alignment: .leading, spacing: 8) {
                Text("Key Topics")
                    .font(.headline)
                    .padding(.bottom, 2)

                FlowLayout(spacing: 6) {
                    ForEach(topics, id: \.self) { topic in
                        Text(topic)
                            .font(.caption)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .background(.blue.opacity(0.08), in: Capsule())
                            .foregroundStyle(.primary)
                    }
                }
            }
            .padding(16)
        }
    }

    // MARK: - Helpers

    private func initials(for name: String) -> String {
        let parts = name.split(separator: " ")
        if parts.count >= 2 {
            return String(parts[0].prefix(1) + parts[1].prefix(1)).uppercased()
        }
        return String(name.prefix(2)).uppercased()
    }

    private func formatTotalDuration(_ seconds: Double) -> String {
        let total = Int(seconds)
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        if hours > 0 {
            return "\(hours)h \(minutes)m"
        }
        return "\(minutes)m"
    }

    private func formatDuration(_ seconds: Double) -> String {
        let total = Int(seconds)
        let minutes = total / 60
        let secs = total % 60
        if minutes > 0 {
            return "\(minutes)m \(secs)s"
        }
        return "\(secs)s"
    }

    private func recencyColor(daysAgo: Int) -> Color {
        if daysAgo <= 7 { return .green }
        if daysAgo <= 30 { return .yellow }
        return .red
    }

    private func recencyLabel(daysAgo: Int) -> String {
        if daysAgo == 0 { return "Spoke today" }
        if daysAgo == 1 { return "Spoke yesterday" }
        if daysAgo <= 7 { return "Spoke \(daysAgo) days ago" }
        if daysAgo <= 30 { return "Spoke \(daysAgo) days ago" }
        let weeks = daysAgo / 7
        if weeks <= 8 { return "Spoke \(weeks) weeks ago" }
        let months = daysAgo / 30
        return "Spoke \(months) months ago"
    }

    /// Extract recurring topics from call summaries (key points + titles)
    private func extractTopics(from calls: [Call]) -> [String] {
        var wordCounts: [String: Int] = [:]

        for call in calls {
            guard let summary = call.summary else { continue }

            // Gather text sources
            var texts: [String] = []
            if let title = summary.title { texts.append(title) }
            if let kp = summary.keyPoints { texts.append(contentsOf: kp) }
            if let decisions = summary.decisions { texts.append(contentsOf: decisions) }

            for text in texts {
                // Extract meaningful phrases (2-3 word sequences)
                let words = text.lowercased()
                    .components(separatedBy: CharacterSet.alphanumerics.inverted)
                    .filter { $0.count > 3 && !stopWords.contains($0) }

                for word in words {
                    wordCounts[word, default: 0] += 1
                }
            }
        }

        // Return words that appear in multiple calls (cross-call topics)
        return wordCounts
            .filter { $0.value >= 2 }
            .sorted { $0.value > $1.value }
            .prefix(12)
            .map { $0.key.capitalized }
    }

    private var stopWords: Set<String> {
        ["this", "that", "with", "from", "they", "have", "been", "were", "will",
         "about", "would", "could", "should", "their", "there", "which", "other",
         "than", "then", "some", "also", "more", "what", "when", "into", "very",
         "just", "need", "only", "does", "done", "said", "each", "make", "like",
         "made", "call", "discussed", "discussed", "mentioned", "agreed"]
    }
}

// MARK: - Timeline Row

private struct TimelineRowView: View {
    let call: Call

    var body: some View {
        HStack(spacing: 10) {
            // Timeline dot + line indicator
            VStack(spacing: 0) {
                Circle()
                    .fill(.blue)
                    .frame(width: 8, height: 8)
            }
            .frame(width: 20)

            Image(systemName: call.appIcon)
                .foregroundStyle(.secondary)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(call.startedAtFormatted)
                        .font(.subheadline)
                        .fontWeight(.medium)

                    Spacer()

                    Text(call.durationFormatted)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }

                HStack(spacing: 6) {
                    Text(call.appName)
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    if call.summary != nil {
                        Image(systemName: "sparkles")
                            .font(.caption2)
                            .foregroundStyle(.purple)
                    }
                }

                if let title = call.callTitle {
                    Text(title)
                        .font(.caption)
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens call details")
    }
}

// MARK: - Person Commitment Row

private struct PersonCommitmentRow: View {
    let commitment: Commitment
    var onComplete: (() -> Void)? = nil
    var onDismiss: (() -> Void)? = nil
    var onNavigate: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: commitment.directionIcon)
                    .font(.caption)
                    .foregroundStyle(commitment.isOutgoing ? .orange : .blue)

                Text(commitment.text)
                    .font(.subheadline)
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

                if let deadline = commitment.deadlineRaw {
                    Label(deadline, systemImage: "calendar")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                if let onComplete {
                    Button("Done", systemImage: "checkmark.circle") { onComplete() }
                        .buttonStyle(.borderless)
                        .font(.caption2)
                        .foregroundStyle(.green)
                }

                if let onDismiss {
                    Button("Dismiss", systemImage: "xmark.circle") { onDismiss() }
                        .buttonStyle(.borderless)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                if let onNavigate {
                    Button("Call", systemImage: "arrow.right.circle") { onNavigate() }
                        .buttonStyle(.borderless)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
        .padding(.horizontal, 8)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 6))
    }
}

// MARK: - Stat Card

private struct StatCard: View {
    let value: String
    let label: String
    let icon: String

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .font(.caption)
                .foregroundStyle(.blue)
            Text(value)
                .font(.title3)
                .fontWeight(.semibold)
                .monospacedDigit()
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(minWidth: 80)
        .padding(.vertical, 8)
        .padding(.horizontal, 4)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
    }
}

// FlowLayout is defined in SummaryView.swift and reused here
