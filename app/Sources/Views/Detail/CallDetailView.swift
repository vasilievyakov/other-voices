import SwiftUI

struct CallDetailView: View {
    let call: Call
    @State private var audioPlayer = AudioPlayer()
    @State private var showTemplatePicker = false
    @Environment(CallStore.self) private var store

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Image(systemName: call.appIcon)
                            .font(.title2)
                        Text(call.appName)
                            .font(.title2)
                            .fontWeight(.semibold)
                        Spacer()

                        Button {
                            showTemplatePicker = true
                        } label: {
                            Label("Template", systemImage: "doc.text")
                                .font(.caption)
                        }
                        .popover(isPresented: $showTemplatePicker) {
                            TemplatePickerView(
                                sessionId: call.sessionId,
                                currentTemplate: call.templateName
                            ) {
                                store.refresh()
                            }
                        }

                        Text(call.durationFormatted)
                            .font(.title3)
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }

                    Text(call.startedAtFormatted)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Divider()

                // Audio Player
                AudioPlayerView(call: call, player: audioPlayer)

                // Notes
                NotesView(sessionId: call.sessionId, initialNotes: call.notes)

                // Summary
                if let summary = call.summary {
                    SummaryView(summary: summary, templateName: call.templateName)
                }

                // Transcript
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
                }

                // Chat
                if call.transcript != nil {
                    Divider()
                    ChatView(sessionId: call.sessionId)
                }
            }
            .padding(20)
        }
        .onDisappear {
            audioPlayer.stop()
        }
    }
}
