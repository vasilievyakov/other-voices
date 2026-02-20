import AVFoundation
import Foundation

@MainActor
@Observable
final class AudioPlayer: NSObject, @preconcurrency AVAudioPlayerDelegate {
    var isPlaying = false
    var currentTime: TimeInterval = 0
    var duration: TimeInterval = 0
    var currentFile: String?
    var playbackSpeed: Float = 1.0

    private var player: AVAudioPlayer?
    private var timer: Timer?

    private static let speeds: [Float] = [0.75, 1.0, 1.25, 1.5, 2.0]

    var speedLabel: String {
        if playbackSpeed == Float(Int(playbackSpeed)) {
            return "\(Int(playbackSpeed))x"
        }
        return String(format: "%.2gx", playbackSpeed)
    }

    func cycleSpeed() {
        guard let idx = Self.speeds.firstIndex(of: playbackSpeed) else {
            playbackSpeed = 1.0
            player?.rate = 1.0
            return
        }
        let next = Self.speeds[(idx + 1) % Self.speeds.count]
        playbackSpeed = next
        player?.rate = next
    }

    func play(path: String) {
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.fileExists(atPath: path) else { return }

        do {
            if currentFile == path && player != nil {
                // Resume
                player?.play()
                isPlaying = true
                startTimer()
                return
            }

            player?.stop()
            player = try AVAudioPlayer(contentsOf: url)
            player?.delegate = self
            player?.enableRate = true
            player?.prepareToPlay()
            player?.rate = playbackSpeed
            duration = player?.duration ?? 0
            currentTime = 0
            currentFile = path
            player?.play()
            isPlaying = true
            startTimer()
        } catch {
            isPlaying = false
        }
    }

    func pause() {
        player?.pause()
        isPlaying = false
        stopTimer()
    }

    func toggle(path: String) {
        if isPlaying && currentFile == path {
            pause()
        } else {
            play(path: path)
        }
    }

    func seek(to time: TimeInterval) {
        player?.currentTime = time
        currentTime = time
    }

    func stop() {
        player?.stop()
        player = nil
        isPlaying = false
        currentTime = 0
        currentFile = nil
        stopTimer()
    }

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        isPlaying = false
        currentTime = 0
        stopTimer()
    }

    private func startTimer() {
        stopTimer()
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self, let player = self.player else { return }
                self.currentTime = player.currentTime
            }
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }
}
