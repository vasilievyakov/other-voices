import SwiftUI

package extension Notification.Name {
    static let togglePlayback = Notification.Name("togglePlayback")
}

struct CallDetailView: View {
    let sessionId: String
    @State private var call: Call?
    @State private var commitments: [Commitment] = []
    @State private var audioPlayer = AudioPlayer()
    @State private var showTemplatePicker = false
    @State private var toastMessage: String?
    @Environment(CallStore.self) private var store
    @Environment(DaemonMonitor.self) private var daemon

    var body: some View {
        Group {
            if let call {
                callContent(call)
            } else {
                ProgressView("Loading...")
            }
        }
        .task(id: sessionId) {
            call = store.getCall(sessionId)
            commitments = store.getCommitments(sessionId: sessionId)
        }
    }

    @ViewBuilder
    private func callContent(_ call: Call) -> some View {
        VStack(spacing: 0) {
            // Sticky header
            header(call)
                .padding(20)
                .background(.bar)

            Divider()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 20) {
                    // Audio Player
                    AudioPlayerView(call: call, player: audioPlayer)

                    // Notes
                    NotesView(sessionId: call.sessionId, initialNotes: call.notes)

                    // Summary
                    summarySection(call)

                    // Commitments
                    commitmentsSection

                    // Transcript
                    transcriptSection(call)

                    // Chat
                    chatSection(call)
                }
                .padding(20)
                .frame(maxWidth: 720, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
        .navigationTitle(call.appName)
        .navigationSubtitle(call.startedAtFormatted)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                exportMenu(call)
            }
            ToolbarItem(placement: .primaryAction) {
                Button { showTemplatePicker = true } label: {
                    Label("Template", systemImage: "doc.text")
                }
                .help("Change summary template")
                .popover(isPresented: $showTemplatePicker) {
                    TemplatePickerView(
                        sessionId: call.sessionId,
                        currentTemplate: call.templateName
                    ) {
                        self.call = store.getCall(sessionId)
                    }
                }
            }
        }
        .overlay(alignment: .bottom) {
            if let message = toastMessage {
                Text(message)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(.ultraThinMaterial, in: Capsule())
                    .shadow(radius: 4)
                    .padding(.bottom, 24)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.25), value: toastMessage)
        .onDisappear {
            audioPlayer.stop()
        }
        .onReceive(NotificationCenter.default.publisher(for: .togglePlayback)) { _ in
            if let path = call.systemWavPath ?? call.micWavPath {
                audioPlayer.toggle(path: path)
            }
        }
    }

    // MARK: - Export Menu

    private func exportMenu(_ call: Call) -> some View {
        Menu {
            Button {
                let md = ExportService.exportAsMarkdown(call: call, commitments: commitments)
                ExportService.copyToClipboard(md)
                showToast("Copied as Markdown")
            } label: {
                Label("Copy as Markdown", systemImage: "doc.richtext")
            }

            Button {
                let text = ExportService.exportAsText(call: call, commitments: commitments)
                ExportService.copyToClipboard(text)
                showToast("Copied as Text")
            } label: {
                Label("Copy as Text", systemImage: "doc.plaintext")
            }

            Divider()

            Button {
                ExportService.saveMarkdownFile(call: call, commitments: commitments)
            } label: {
                Label("Save as Markdown File...", systemImage: "square.and.arrow.down")
            }
        } label: {
            Label("Export", systemImage: "square.and.arrow.up")
        }
        .help("Export call data")
    }

    private func showToast(_ message: String) {
        toastMessage = message
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            if toastMessage == message {
                toastMessage = nil
            }
        }
    }

    // MARK: - Header

    private func header(_ call: Call) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: call.appIcon)
                    .font(.title2)
                    .accessibilityHidden(true)
                Text(call.appName)
                    .font(.title2)
                    .fontWeight(.semibold)
                Spacer()

                Text(call.durationFormatted)
                    .font(.title3)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }

            Text(call.startedAtFormatted)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Processing Placeholder

    private func processingPlaceholder(title: String, icon: String, message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: icon)
                .font(.title3)
                .fontWeight(.semibold)
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(message).font(.subheadline).foregroundStyle(.secondary)
            }
            .accessibilityElement(children: .combine)
        }
    }

    // MARK: - Summary Section

    @ViewBuilder
    private func summarySection(_ call: Call) -> some View {
        if let summary = call.summary {
            SummaryView(summary: summary, templateName: call.templateName)
        } else if call.summaryJson != nil {
            // JSON exists but decode failed completely
            VStack(alignment: .leading, spacing: 8) {
                Label("Summary", systemImage: "sparkles")
                    .font(.title3)
                    .fontWeight(.semibold)

                Label("Summary format not recognized", systemImage: "exclamationmark.triangle")
                    .font(.subheadline)
                    .foregroundStyle(.orange)

                if let raw = call.summaryJson {
                    Text(raw.prefix(500))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .padding(8)
                        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 6))
                }
            }
        } else if daemon.status?.isProcessing == true {
            processingPlaceholder(
                title: "Summary",
                icon: "sparkles",
                message: "Generating summary..."
            )
        } else {
            VStack(alignment: .leading, spacing: 4) {
                Label("No Summary", systemImage: "sparkles")
                    .font(.title3)
                    .fontWeight(.semibold)
                Text("This call has no AI-generated summary yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Transcript Section

    @ViewBuilder
    private func transcriptSection(_ call: Call) -> some View {
        if let transcript = call.transcript, !transcript.isEmpty {
            TranscriptView(
                transcript: transcript,
                segments: call.transcriptSegments,
                onSeek: { time in
                    if let path = call.systemWavPath ?? call.micWavPath {
                        audioPlayer.play(path: path)
                        audioPlayer.seek(to: time)
                    }
                }
            )
        } else if daemon.status?.isProcessing == true {
            processingPlaceholder(
                title: "Transcript",
                icon: "text.alignleft",
                message: "Transcribing audio..."
            )
        } else {
            VStack(alignment: .leading, spacing: 4) {
                Label("No Transcript", systemImage: "text.alignleft")
                    .font(.title3)
                    .fontWeight(.semibold)
                Text("Transcript is not available for this call.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    // MARK: - Commitments Section

    @ViewBuilder
    private var commitmentsSection: some View {
        if !commitments.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Label("Commitments", systemImage: "handshake.fill")
                    .font(.title3)
                    .fontWeight(.semibold)

                ForEach(commitments) { commitment in
                    HStack(spacing: 8) {
                        Image(systemName: commitment.directionIcon)
                            .foregroundStyle(commitment.isOutgoing ? .orange : .blue)
                            .font(.caption)

                        VStack(alignment: .leading, spacing: 2) {
                            Text(commitment.text)
                                .font(.subheadline)
                            if let deadline = commitment.deadlineRaw {
                                Text("Deadline: \(deadline)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }

                        Spacer()

                        if commitment.isOpen {
                            Button {
                                store.updateCommitmentStatus(id: commitment.id, status: "done")
                                commitments = store.getCommitments(sessionId: sessionId)
                            } label: {
                                Image(systemName: "checkmark.circle")
                            }
                            .buttonStyle(.borderless)
                            .foregroundStyle(.green)
                            .help("Mark as done")
                        } else {
                            Image(systemName: commitment.statusIcon)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 2)
                }
            }
        }
    }

    // MARK: - Chat Section

    @ViewBuilder
    private func chatSection(_ call: Call) -> some View {
        if call.transcript != nil {
            Divider()
            ChatView(sessionId: call.sessionId)
        }
    }
}
