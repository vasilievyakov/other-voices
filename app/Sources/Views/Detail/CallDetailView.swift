import SwiftUI

struct CallDetailView: View {
    let call: Call
    @State private var audioPlayer = AudioPlayer()

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

                // Summary
                if let summary = call.summary {
                    SummaryView(summary: summary)
                }

                // Transcript
                if let transcript = call.transcript, !transcript.isEmpty {
                    TranscriptView(transcript: transcript)
                }
            }
            .padding(20)
        }
        .onDisappear {
            audioPlayer.stop()
        }
    }
}
