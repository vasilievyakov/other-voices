import SwiftUI

package struct WelcomeView: View {
    @Environment(DaemonMonitor.self) private var daemon
    @Binding var hasCompletedOnboarding: Bool

    @State private var ollamaAvailable: Bool?
    @State private var appeared = false

    package init(hasCompletedOnboarding: Binding<Bool>) {
        self._hasCompletedOnboarding = hasCompletedOnboarding
    }

    package var body: some View {
        VStack(spacing: 0) {
            Spacer()

            // App icon
            Image(systemName: "waveform.circle.fill")
                .font(.system(size: 72))
                .foregroundStyle(.tint)
                .symbolRenderingMode(.hierarchical)
                .opacity(appeared ? 1 : 0)
                .offset(y: appeared ? 0 : 10)
                .animation(.easeOut(duration: 0.6), value: appeared)
                .padding(.bottom, 16)

            // Title
            Text("Other Voices")
                .font(.system(size: 32, weight: .bold, design: .default))
                .opacity(appeared ? 1 : 0)
                .animation(.easeOut(duration: 0.6).delay(0.1), value: appeared)

            // Subtitle
            Text("Your calls, your insights, your privacy.")
                .font(.title3)
                .foregroundStyle(.secondary)
                .opacity(appeared ? 1 : 0)
                .animation(.easeOut(duration: 0.6).delay(0.2), value: appeared)
                .padding(.bottom, 32)

            // Feature highlights
            VStack(alignment: .leading, spacing: 16) {
                FeatureRow(
                    icon: "phone.badge.waveform.fill",
                    title: "Automatic Recording",
                    subtitle: "Detects calls and records transparently"
                )
                FeatureRow(
                    icon: "sparkles",
                    title: "AI Summaries",
                    subtitle: "Local AI extracts key points, decisions, and commitments"
                )
                FeatureRow(
                    icon: "lock.shield.fill",
                    title: "Complete Privacy",
                    subtitle: "Everything stays on your Mac, nothing leaves"
                )
            }
            .opacity(appeared ? 1 : 0)
            .offset(y: appeared ? 0 : 8)
            .animation(.easeOut(duration: 0.5).delay(0.35), value: appeared)
            .padding(.bottom, 32)

            // Status checks
            VStack(spacing: 10) {
                StatusRow(
                    label: "Recording Daemon",
                    isAvailable: daemon.isAvailable
                )
                StatusRow(
                    label: "Ollama AI Engine",
                    isAvailable: ollamaAvailable
                )
            }
            .padding(16)
            .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
            .opacity(appeared ? 1 : 0)
            .animation(.easeOut(duration: 0.5).delay(0.5), value: appeared)
            .padding(.bottom, 32)

            // Get Started button
            Button {
                withAnimation(.easeInOut(duration: 0.3)) {
                    hasCompletedOnboarding = true
                }
            } label: {
                Text("Get Started")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .opacity(appeared ? 1 : 0)
            .animation(.easeOut(duration: 0.5).delay(0.6), value: appeared)

            Spacer()
        }
        .padding(.horizontal, 48)
        .frame(maxWidth: 500)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
        .task {
            appeared = true
            await checkOllama()
        }
    }

    private func checkOllama() async {
        guard let url = URL(string: "http://localhost:11434/api/tags") else {
            ollamaAvailable = false
            return
        }
        do {
            let (_, response) = try await URLSession.shared.data(from: url)
            if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                ollamaAvailable = true
            } else {
                ollamaAvailable = false
            }
        } catch {
            ollamaAvailable = false
        }
    }
}

// MARK: - Feature Row

private struct FeatureRow: View {
    let icon: String
    let title: String
    let subtitle: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundStyle(.tint)
                .frame(width: 32, alignment: .center)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

// MARK: - Status Row

private struct StatusRow: View {
    let label: String
    let isAvailable: Bool?

    var body: some View {
        HStack(spacing: 10) {
            Group {
                if let available = isAvailable {
                    Image(systemName: available ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundStyle(available ? .green : .red)
                } else {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .frame(width: 18, alignment: .center)

            Text(label)
                .font(.subheadline)

            Spacer()

            if let available = isAvailable {
                Text(available ? "Available" : "Not Running")
                    .font(.caption)
                    .foregroundStyle(available ? .green : .secondary)
            } else {
                Text("Checking...")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
