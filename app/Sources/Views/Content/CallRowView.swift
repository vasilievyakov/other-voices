import SwiftUI

struct CallRowView: View {
    let call: Call

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: call.appIcon)
                .foregroundStyle(.secondary)
                .frame(width: 24)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(call.appName)
                        .fontWeight(.medium)

                    if call.summary != nil {
                        Image(systemName: "sparkles")
                            .font(.caption2)
                            .foregroundStyle(.purple)
                            .accessibilityLabel("AI summary available")
                    }

                    Spacer()
                    Text(call.durationFormatted)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }

                if let title = call.callTitle {
                    Text(title)
                        .font(.subheadline)
                        .lineLimit(1)
                }

                Text(call.startedAtFormatted)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if let summary = call.summary?.summary {
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 2)
        .accessibilityElement(children: .combine)
    }
}
