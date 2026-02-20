import SwiftUI

struct DaemonStatusCard: View {
    @Environment(DaemonMonitor.self) private var daemon

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)
                    .overlay(
                        Circle()
                            .fill(statusColor.opacity(0.4))
                            .frame(width: 16, height: 16)
                            .opacity(daemon.status?.isRecording == true ? 1 : 0)
                            .animation(.easeInOut(duration: 1).repeatForever(autoreverses: true),
                                       value: daemon.status?.isRecording)
                    )

                Text(statusTitle)
                    .font(.headline)
                    .fontWeight(.medium)

                Spacer()
            }

            if let status = daemon.status {
                if status.isRecording, let app = status.appName {
                    HStack {
                        Text("Recording: \(app)")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                    if let dur = daemon.recordingDuration {
                        Text("Duration: \(formatDuration(dur))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                }

                if status.isProcessing {
                    HStack(spacing: 4) {
                        ProgressView()
                            .controlSize(.small)
                        Text(status.stateLabel)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .padding(10)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }

    private var statusColor: Color {
        guard let status = daemon.status else { return .gray }
        switch status.state {
        case "recording": return .red
        case "processing": return .orange
        case "idle": return .green
        default: return .gray
        }
    }

    private var statusTitle: String {
        guard let status = daemon.status else { return "Daemon Offline" }
        switch status.state {
        case "recording": return "Recording"
        case "processing": return "Processing"
        case "idle": return "Daemon Active"
        default: return "Daemon Stopped"
        }
    }

    private func formatDuration(_ interval: TimeInterval) -> String {
        let total = Int(interval)
        let minutes = total / 60
        let seconds = total % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }
}
