import SwiftUI

struct DaemonStatusCard: View {
    @Environment(DaemonMonitor.self) private var daemon
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let status = daemon.status {
                if status.isRecording {
                    recordingView(status)
                } else if status.isProcessing {
                    processingView(status)
                } else {
                    listeningView
                }

                // Ollama warning — only when daemon is running but AI is unavailable
                if !daemon.ollamaAvailable {
                    ollamaWarningView
                }
            } else {
                offlineView
            }
        }
        .padding(10)
        .background(cardBackground, in: RoundedRectangle(cornerRadius: 8))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibleDescription)
    }

    // MARK: - Listening (idle)

    private var listeningView: some View {
        HStack(spacing: 8) {
            Image(systemName: "waveform")
                .foregroundStyle(.secondary)
                .font(.system(size: 12, weight: .medium))
                .frame(width: 16)

            Text("Listening for calls")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Spacer()
        }
    }

    // MARK: - Recording (hero state)

    private func recordingView(_ status: DaemonStatus) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                recordingDot

                VStack(alignment: .leading, spacing: 1) {
                    Text("Recording \(status.appName ?? "call")")
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .foregroundStyle(.primary)

                    if let dur = daemon.recordingDuration {
                        Text(formatDuration(dur))
                            .font(.caption)
                            .fontWeight(.medium)
                            .foregroundStyle(.red.opacity(0.8))
                            .monospacedDigit()
                    }
                }

                Spacer()
            }
        }
    }

    private var recordingDot: some View {
        Circle()
            .fill(.red)
            .frame(width: 8, height: 8)
            .overlay(
                Circle()
                    .fill(.red.opacity(0.4))
                    .frame(width: 16, height: 16)
                    .opacity(reduceMotion ? 0 : 1)
                    .animation(
                        .easeInOut(duration: 1.0).repeatForever(autoreverses: true),
                        value: daemon.status?.isRecording
                    )
            )
            .frame(width: 16)
    }

    // MARK: - Processing

    private func processingView(_ status: DaemonStatus) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                ProgressView()
                    .controlSize(.small)

                Text("Processing your call\u{2026}")
                    .font(.subheadline)
                    .foregroundStyle(.primary)

                Spacer()
            }

            // Pipeline stage indicator
            VStack(alignment: .leading, spacing: 4) {
                ProgressView(value: status.pipelineProgress)
                    .tint(.orange)

                Text(status.pipelineUserLabel)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Offline (daemon not running)

    private var offlineView: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.yellow)
                    .font(.system(size: 12))
                    .frame(width: 16)

                Text("Not monitoring")
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundStyle(.primary)

                Spacer()
            }

            Text("Calls won\u{2019}t be recorded. Start the daemon with **launchctl**.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - Ollama warning

    private var ollamaWarningView: some View {
        HStack(spacing: 6) {
            Image(systemName: "brain")
                .foregroundStyle(.orange)
                .font(.system(size: 10))

            Text("AI unavailable \u{2014} calls recorded, not summarized")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 6)
    }

    // MARK: - Card background

    private var cardBackground: some ShapeStyle {
        if let status = daemon.status, status.isRecording {
            return AnyShapeStyle(.red.opacity(0.06))
        }
        return AnyShapeStyle(.quaternary.opacity(0.5))
    }

    // MARK: - Accessibility

    private var accessibleDescription: String {
        guard let status = daemon.status else {
            return "Not monitoring calls. Start the daemon to record automatically."
        }
        switch status.state {
        case "recording":
            let app = status.appName ?? "call"
            let dur = daemon.recordingDuration.map { formatDuration($0) } ?? ""
            return "Recording \(app). \(dur)"
        case "processing":
            return "Processing your call. \(status.pipelineUserLabel)."
        case "idle":
            return "Listening for calls."
        default:
            return "Status: \(status.stateLabel)"
        }
    }

    // MARK: - Helpers

    private func formatDuration(_ interval: TimeInterval) -> String {
        let total = Int(interval)
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let seconds = total % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, seconds)
        }
        return String(format: "%02d:%02d", minutes, seconds)
    }
}
