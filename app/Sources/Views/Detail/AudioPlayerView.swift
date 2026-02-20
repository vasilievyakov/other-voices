import SwiftUI

struct AudioPlayerView: View {
    let call: Call
    @Bindable var player: AudioPlayer

    var body: some View {
        if call.systemWavPath == nil && call.micWavPath == nil {
            VStack(alignment: .leading, spacing: 8) {
                Label("Audio", systemImage: "waveform")
                    .font(.title3)
                    .fontWeight(.semibold)
                Text("No audio files available for this call.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        } else {
            VStack(alignment: .leading, spacing: 12) {
                Label("Audio", systemImage: "waveform")
                    .font(.title3)
                    .fontWeight(.semibold)

                if let systemPath = call.systemWavPath,
                   FileManager.default.fileExists(atPath: systemPath) {
                    audioRow(label: "System Audio", path: systemPath)
                }

                if let micPath = call.micWavPath,
                   FileManager.default.fileExists(atPath: micPath) {
                    audioRow(label: "Microphone", path: micPath)
                }
            }
        }
    }

    @ViewBuilder
    private func audioRow(label: String, path: String) -> some View {
        HStack(spacing: 12) {
            Button {
                player.toggle(path: path)
            } label: {
                Image(systemName: player.isPlaying && player.currentFile == path
                    ? "pause.circle.fill" : "play.circle.fill")
                    .font(.title2)
            }
            .buttonStyle(.borderless)
            .help(player.isPlaying && player.currentFile == path ? "Pause" : "Play \(label.lowercased())")
            .accessibilityLabel(player.isPlaying && player.currentFile == path ? "Pause" : "Play")

            Text(label)
                .font(.subheadline)
                .frame(minWidth: 85, alignment: .leading)
                .fixedSize()

            if player.currentFile == path && player.duration > 0 {
                Slider(
                    value: Binding(
                        get: { player.currentTime },
                        set: { player.seek(to: $0) }
                    ),
                    in: 0...player.duration
                )
                .accessibilityLabel("Playback position")
                .accessibilityValue("\(formatTime(player.currentTime)) of \(formatTime(player.duration))")

                Text("\(formatTime(player.currentTime)) / \(formatTime(player.duration))")
                    .font(.caption)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .frame(minWidth: 85)
                    .fixedSize()

                Button {
                    player.cycleSpeed()
                } label: {
                    Text(player.speedLabel)
                        .font(.caption)
                        .monospacedDigit()
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 4))
                }
                .buttonStyle(.borderless)
                .help("Playback speed")
                .accessibilityLabel("Playback speed \(player.speedLabel)")
            } else {
                Spacer()
            }
        }
        .padding(.vertical, 4)
    }

    private func formatTime(_ time: TimeInterval) -> String {
        let total = Int(time)
        let minutes = total / 60
        let seconds = total % 60
        return String(format: "%d:%02d", minutes, seconds)
    }
}
