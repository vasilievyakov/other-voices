import Foundation

/// Monitors a directory for file changes using DispatchSource (kqueue).
/// We watch the directory (not the file) because the daemon writes atomically via os.replace.
final class StatusMonitor {
    private var source: DispatchSourceFileSystemObject?
    private let directoryPath: String
    private let onChange: @Sendable () -> Void

    init(directoryPath: String, onChange: @escaping @Sendable () -> Void) {
        self.directoryPath = directoryPath
        self.onChange = onChange
    }

    func start() {
        let fd = Darwin.open(directoryPath, O_EVTONLY)
        guard fd >= 0 else { return }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fd,
            eventMask: .write,
            queue: .main
        )
        source.setEventHandler { [weak self] in
            self?.onChange()
        }
        source.setCancelHandler {
            Darwin.close(fd)
        }
        source.resume()
        self.source = source
    }

    func stop() {
        source?.cancel()
        source = nil
    }

    deinit {
        stop()
    }
}
