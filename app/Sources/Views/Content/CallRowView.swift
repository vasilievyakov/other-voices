import SwiftUI

struct CallRowView: View {
    let call: Call

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: call.appIcon)
                .foregroundStyle(.secondary)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(call.appName)
                        .fontWeight(.medium)
                    Spacer()
                    Text(call.durationFormatted)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }

                Text(call.startedAtFormatted)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if let summary = call.summary?.summary {
                    Text(summary)
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 2)
    }
}
