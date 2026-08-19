import AudioToolbox
import AVFoundation
import CoreAudio
import CoreMedia
import Foundation
import ScreenCaptureKit

// MARK: - Audio Capture CLI
// Usage: audio-capture <output-dir> <session-id>
// Captures system audio via ScreenCaptureKit and microphone via AVAudioEngine
// Stops gracefully on SIGTERM, finalizing WAV files

let sampleRate: Double = 16000
let channels: AVAudioChannelCount = 1

// MARK: - WAV File Writer

class WAVWriter {
    private let fileHandle: FileHandle
    private let filePath: String
    private var dataSize: UInt32 = 0
    private let bytesPerSample: UInt16 = 2  // 16-bit PCM

    init(path: String, sampleRate: UInt32, channels: UInt16) throws {
        FileManager.default.createFile(atPath: path, contents: nil)
        self.filePath = path
        self.fileHandle = try FileHandle(forWritingTo: URL(fileURLWithPath: path))

        // Write WAV header placeholder (44 bytes)
        var header = Data(count: 44)

        // RIFF chunk
        header[0...3] = Data("RIFF".utf8)
        // File size placeholder (filled on finalize)
        header[4...7] = Data(repeating: 0, count: 4)
        header[8...11] = Data("WAVE".utf8)

        // fmt sub-chunk
        header[12...15] = Data("fmt ".utf8)
        withUnsafeBytes(of: UInt32(16).littleEndian) { header[16...19] = Data($0) }  // sub-chunk size
        withUnsafeBytes(of: UInt16(1).littleEndian) { header[20...21] = Data($0) }  // PCM format
        withUnsafeBytes(of: channels.littleEndian) { header[22...23] = Data($0) }
        withUnsafeBytes(of: sampleRate.littleEndian) { header[24...27] = Data($0) }
        let byteRate = sampleRate * UInt32(channels) * UInt32(bytesPerSample)
        withUnsafeBytes(of: byteRate.littleEndian) { header[28...31] = Data($0) }
        let blockAlign = channels * bytesPerSample
        withUnsafeBytes(of: blockAlign.littleEndian) { header[32...33] = Data($0) }
        withUnsafeBytes(of: (bytesPerSample * 8).littleEndian) { header[34...35] = Data($0) }  // bits per sample

        // data sub-chunk
        header[36...39] = Data("data".utf8)
        // Data size placeholder (filled on finalize)
        header[40...43] = Data(repeating: 0, count: 4)

        fileHandle.write(header)
    }

    func writeSamples(_ data: Data) {
        fileHandle.write(data)
        dataSize += UInt32(data.count)
    }

    func finalize() {
        // Update data size
        fileHandle.seek(toFileOffset: 40)
        var ds = dataSize.littleEndian
        fileHandle.write(Data(bytes: &ds, count: 4))

        // Update RIFF size
        fileHandle.seek(toFileOffset: 4)
        var riffSize = (dataSize + 36).littleEndian
        fileHandle.write(Data(bytes: &riffSize, count: 4))

        fileHandle.closeFile()
    }
}

// MARK: - System Audio Capture (ScreenCaptureKit)

class SystemAudioCapture: NSObject, SCStreamDelegate, SCStreamOutput {
    private var stream: SCStream?
    private var wavWriter: WAVWriter?
    private let outputPath: String
    private var isRunning = false

    init(outputPath: String) {
        self.outputPath = outputPath
        super.init()
    }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)

        guard let display = content.displays.first else {
            throw NSError(domain: "AudioCapture", code: 1, userInfo: [NSLocalizedDescriptionKey: "No display found"])
        }

        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = Int(sampleRate)
        config.channelCount = Int(channels)

        // We only need audio, minimize video overhead
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)  // 1 fps minimum

        wavWriter = try WAVWriter(path: outputPath, sampleRate: UInt32(sampleRate), channels: UInt16(channels))

        stream = SCStream(filter: filter, configuration: config, delegate: self)
        try stream!.addStreamOutput(self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "system-audio"))

        try await stream!.startCapture()
        isRunning = true
        fputs("System audio capture started: \(outputPath)\n", stderr)
    }

    func stop() async {
        guard isRunning, let stream = stream else { return }
        do {
            try await stream.stopCapture()
        } catch {
            fputs("Warning: error stopping system audio stream: \(error)\n", stderr)
        }
        wavWriter?.finalize()
        isRunning = false
        fputs("System audio capture stopped, WAV finalized\n", stderr)
    }

    // SCStreamOutput — receive audio buffers
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }

        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &dataPointer)

        guard let dataPointer = dataPointer, length > 0 else { return }

        // Get the audio format to check if conversion is needed
        guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else {
            return
        }

        if asbd.pointee.mFormatFlags & kAudioFormatFlagIsFloat != 0 {
            // Convert Float32 to Int16
            let floatCount = length / MemoryLayout<Float32>.size
            let floatPtr = UnsafeRawPointer(dataPointer).bindMemory(to: Float32.self, capacity: floatCount)
            var int16Data = Data(count: floatCount * MemoryLayout<Int16>.size)
            int16Data.withUnsafeMutableBytes { rawBuffer in
                let int16Ptr = rawBuffer.bindMemory(to: Int16.self)
                for i in 0..<floatCount {
                    let clamped = max(-1.0, min(1.0, floatPtr[i]))
                    int16Ptr[i] = Int16(clamped * Float32(Int16.max))
                }
            }
            wavWriter?.writeSamples(int16Data)
        } else {
            // Already Int16 PCM
            let data = Data(bytes: dataPointer, count: length)
            wavWriter?.writeSamples(data)
        }
    }

    // SCStreamDelegate
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("System audio stream stopped with error: \(error)\n", stderr)
        wavWriter?.finalize()
        isRunning = false
    }
}

// MARK: - Microphone Capture (AVAudioEngine)

class MicrophoneCapture {
    private let engine = AVAudioEngine()
    private var wavWriter: WAVWriter?
    private let outputPath: String
    private var configObserver: NSObjectProtocol?
    private let preferredDevice: String?

    init(outputPath: String, preferredDevice: String? = nil) {
        self.outputPath = outputPath
        self.preferredDevice = preferredDevice
    }

    /// Find an input-capable CoreAudio device by exact name.
    private func findInputDevice(named name: String) -> AudioDeviceID? {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size
        ) == noErr else { return nil }
        var ids = [AudioDeviceID](
            repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size
        )
        guard AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &ids
        ) == noErr else { return nil }

        for id in ids {
            var nameAddress = AudioObjectPropertyAddress(
                mSelector: kAudioObjectPropertyName,
                mScope: kAudioObjectPropertyScopeGlobal,
                mElement: kAudioObjectPropertyElementMain
            )
            var deviceName: CFString? = nil
            var nameSize = UInt32(MemoryLayout<CFString?>.size)
            let status = withUnsafeMutablePointer(to: &deviceName) { ptr in
                AudioObjectGetPropertyData(id, &nameAddress, 0, nil, &nameSize, ptr)
            }
            guard status == noErr, (deviceName as String?) == name else { continue }

            var streamsAddress = AudioObjectPropertyAddress(
                mSelector: kAudioDevicePropertyStreams,
                mScope: kAudioDevicePropertyScopeInput,
                mElement: kAudioObjectPropertyElementMain
            )
            var streamsSize: UInt32 = 0
            if AudioObjectGetPropertyDataSize(id, &streamsAddress, 0, nil, &streamsSize)
                == noErr, streamsSize > 0 {
                return id
            }
        }
        return nil
    }

    /// Pin the engine's input to a specific device. The system default input
    /// (a Bluetooth headset mic) returns zero-filled buffers while a call app
    /// holds it — a USB mic is immune to that contention.
    private func pinInputDevice() {
        guard let name = preferredDevice, !name.isEmpty else { return }
        guard var deviceID = findInputDevice(named: name) else {
            fputs("Input device '\(name)' not found — using default input\n", stderr)
            return
        }
        guard let audioUnit = engine.inputNode.audioUnit else {
            fputs("No input audio unit — using default input\n", stderr)
            return
        }
        let status = AudioUnitSetProperty(
            audioUnit,
            kAudioOutputUnitProperty_CurrentDevice,
            kAudioUnitScope_Global,
            0,
            &deviceID,
            UInt32(MemoryLayout<AudioDeviceID>.size)
        )
        if status == noErr {
            fputs("Microphone input pinned to: \(name)\n", stderr)
        } else {
            fputs(
                "Failed to pin input to '\(name)' (status \(status)) — using default\n",
                stderr
            )
        }
    }

    func start() throws {
        // WAV writer is created once and reused across engine restarts, so a
        // mid-call route change keeps appending to the same file.
        wavWriter = try WAVWriter(path: outputPath, sampleRate: UInt32(sampleRate), channels: UInt16(channels))
        try startEngine()

        // AVAudioEngine silently stops delivering buffers when the audio
        // route/config changes — e.g. an output/input device switch, or another
        // app (a dictation tool like Wispr Flow) grabbing the microphone. Left
        // unhandled, the tap goes quiet and mic.wav ends up empty (header only).
        // Restart the engine on every configuration change to keep capturing.
        configObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange,
            object: engine,
            queue: nil
        ) { [weak self] _ in
            self?.restartAfterConfigChange()
        }

        fputs("Microphone capture started: \(outputPath)\n", stderr)
    }

    private func startEngine() throws {
        pinInputDevice()
        let inputNode = engine.inputNode
        let hwFormat = inputNode.inputFormat(forBus: 0)
        fputs("Microphone hw format: \(Int(hwFormat.sampleRate)) Hz, \(hwFormat.channelCount) ch\n", stderr)

        guard hwFormat.sampleRate > 0 else {
            throw NSError(domain: "AudioCapture", code: 2, userInfo: [NSLocalizedDescriptionKey: "No microphone available"])
        }

        // Target format: 16kHz mono Int16
        guard let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: sampleRate,
            channels: channels,
            interleaved: true
        ) else {
            throw NSError(domain: "AudioCapture", code: 3, userInfo: [NSLocalizedDescriptionKey: "Cannot create target audio format"])
        }

        // Install tap with converter (re-created each start to match current hw format)
        let converter = AVAudioConverter(from: hwFormat, to: targetFormat)

        inputNode.installTap(onBus: 0, bufferSize: 4096, format: hwFormat) { [weak self] buffer, _ in
            guard let self = self, let converter = converter else { return }

            let frameCapacity = AVAudioFrameCount(
                Double(buffer.frameLength) * sampleRate / hwFormat.sampleRate
            )
            guard frameCapacity > 0 else { return }

            guard let convertedBuffer = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: frameCapacity) else { return }

            var error: NSError?
            var allConsumed = false
            converter.convert(to: convertedBuffer, error: &error) { _, outStatus in
                if allConsumed {
                    outStatus.pointee = .noDataNow
                    return nil
                }
                allConsumed = true
                outStatus.pointee = .haveData
                return buffer
            }

            if let error = error {
                fputs("Conversion error: \(error)\n", stderr)
                return
            }

            guard convertedBuffer.frameLength > 0 else { return }

            let byteCount = Int(convertedBuffer.frameLength) * Int(channels) * MemoryLayout<Int16>.size
            if let channelData = convertedBuffer.int16ChannelData {
                let data = Data(bytes: channelData[0], count: byteCount)
                self.wavWriter?.writeSamples(data)
            }
        }

        try engine.start()
    }

    private func restartAfterConfigChange() {
        fputs("Audio configuration changed — restarting microphone engine\n", stderr)
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        do {
            try startEngine()
            fputs("Microphone engine restarted after config change\n", stderr)
        } catch {
            fputs("Failed to restart microphone after config change: \(error)\n", stderr)
        }
    }

    func stop() {
        if let observer = configObserver {
            NotificationCenter.default.removeObserver(observer)
            configObserver = nil
        }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        wavWriter?.finalize()
        fputs("Microphone capture stopped, WAV finalized\n", stderr)
    }
}

// MARK: - Main

guard CommandLine.arguments.count >= 3 else {
    fputs("Usage: audio-capture <output-dir> <session-id>\n", stderr)
    exit(1)
}

let outputDir = CommandLine.arguments[1]
let sessionId = CommandLine.arguments[2]
// Optional: preferred input device name (argv[3]); empty = system default
let preferredMic = CommandLine.arguments.count >= 4 ? CommandLine.arguments[3] : nil

let systemPath = "\(outputDir)/system.wav"
let micPath = "\(outputDir)/mic.wav"

// Create output directory
try FileManager.default.createDirectory(atPath: outputDir, withIntermediateDirectories: true)

let systemCapture = SystemAudioCapture(outputPath: systemPath)
let micCapture = MicrophoneCapture(outputPath: micPath, preferredDevice: preferredMic)

var shouldStop = false

// Handle SIGTERM for graceful shutdown
signal(SIGTERM, SIG_IGN)
let termSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
termSource.setEventHandler {
    fputs("Received SIGTERM, stopping capture...\n", stderr)
    shouldStop = true
}
termSource.resume()

// Handle SIGINT too
signal(SIGINT, SIG_IGN)
let intSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
intSource.setEventHandler {
    fputs("Received SIGINT, stopping capture...\n", stderr)
    shouldStop = true
}
intSource.resume()

// Start captures
Task {
    do {
        try await systemCapture.start()
    } catch {
        let msg = "Failed to start system audio capture: \(error)"
        fputs("\(msg)\n", stderr)
        fputs("Make sure Screen Recording permission is granted.\n", stderr)
        // Drop a marker file so the Python pipeline can deterministically detect
        // that system audio capture failed (e.g. Screen Recording TCC declined),
        // instead of guessing from an empty/missing system.wav. daemon.py reads
        // this to warn the user and flag status.json.
        let markerPath = "\(outputDir)/capture-error.txt"
        try? "\(msg)\nMake sure Screen Recording permission is granted.\n"
            .write(toFile: markerPath, atomically: true, encoding: .utf8)
    }

    do {
        try micCapture.start()
    } catch {
        fputs("Failed to start microphone capture: \(error)\n", stderr)
        fputs("Make sure Microphone permission is granted.\n", stderr)
    }

    fputs("Recording session: \(sessionId)\n", stderr)
    fputs("Press Ctrl+C or send SIGTERM to stop.\n", stderr)
}

// Run loop — check for stop flag
Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { timer in
    if shouldStop {
        timer.invalidate()

        Task {
            await systemCapture.stop()
            micCapture.stop()
            fputs("All captures finalized. Exiting.\n", stderr)
            exit(0)
        }
    }
}

RunLoop.main.run()
