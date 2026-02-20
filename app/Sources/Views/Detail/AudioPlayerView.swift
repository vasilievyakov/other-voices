import SwiftUI

struct AudioPlayerView: View {
    let call: Call
    @Bindable var player: AudioPlayer

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
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

            Text(label)
                .font(.subheadline)
                .frame(width: 100, alignment: .leading)

            if player.currentFile == path && player.duration > 0 {
                Slider(
                    value: Binding(
                        get: { player.currentTime },
                        set: { player.seek(to: $0) }
                    ),
                    in: 0...player.duration
                )

                Text(formatTime(player.currentTime))
                    .font(.caption)
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
                    .frame(width: 45)
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
