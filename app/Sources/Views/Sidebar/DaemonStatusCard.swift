import SwiftUI

struct DaemonStatusCard: View {
    @Environment(DaemonMonitor.self) private var daemon
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: statusSymbol)
                    .foregroundStyle(statusColor)
                    .font(.system(size: 8))
                    .overlay(
                        Circle()
                            .fill(statusColor.opacity(0.4))
                            .frame(width: 16, height: 16)
                            .opacity(daemon.status?.isRecording == true ? 1 : 0)
                            .animation(
                                reduceMotion ? nil : .easeInOut(duration: 1).repeatForever(autoreverses: true),
                                value: daemon.status?.isRecording
                            )
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
            } else {
                Text("Start the daemon to record calls automatically.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)

                Button {
                    NSWorkspace.shared.open(URL(string: "https://github.com/vasilievyakov/other-voices#setup")!)
                } label: {
                    Label("How to start", systemImage: "questionmark.circle")
                        .font(.caption)
                }
                .buttonStyle(.borderless)
            }
        }
        .padding(10)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibleStatusDescription)
    }

    private var statusSymbol: String {
        switch daemon.status?.state {
        case "recording": return "record.circle.fill"
        case "processing": return "gearshape.fill"
        case "idle": return "checkmark.circle.fill"
        default: return "xmark.circle.fill"
        }
    }

    private var accessibleStatusDescription: String {
        guard let status = daemon.status else {
            return "Daemon offline"
        }
        switch status.state {
        case "recording":
            return "Recording \(status.appName ?? "call")"
        case "processing":
            return "Processing: \(status.stateLabel)"
        case "idle":
            return "Daemon active, idle"
        default:
            return "Daemon status: \(status.stateLabel)"
        }
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
