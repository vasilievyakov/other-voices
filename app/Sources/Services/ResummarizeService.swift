import Foundation
import OSLog

private let logger = Logger(subsystem: "com.user.other-voices", category: "resummarize")

@Observable
final class ResummarizeService {
    var isProcessing = false
    var error: String?

    func resummarize(sessionId: String, templateName: String, completion: @escaping () -> Void) {
        guard !isProcessing else { return }
        isProcessing = true
        error = nil

        Task.detached { [weak self] in
            let pythonPath = NSHomeDirectory() + "/call-recorder/.venv/bin/python"
            let scriptPath = NSHomeDirectory() + "/call-recorder/resummarize.py"

            let process = Process()
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = ["--", scriptPath, "--session", sessionId, "--template", templateName]
            process.currentDirectoryURL = URL(fileURLWithPath: NSHomeDirectory() + "/call-recorder")

            // Use the Python executable directly with the script as argument
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [scriptPath, "--session", sessionId, "--template", templateName]

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            do {
                try process.run()
                process.waitUntilExit()

                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8) ?? ""

                await MainActor.run {
                    if process.terminationStatus == 0 {
                        logger.info("Re-summarize OK: \(output)")
                        self?.error = nil
                    } else {
                        logger.error("Re-summarize failed: \(output)")
                        self?.error = "Re-summarization failed"
                    }
                    self?.isProcessing = false
                    completion()
                }
            } catch {
                logger.error("Process launch failed: \(error.localizedDescription)")
                await MainActor.run {
                    self?.error = error.localizedDescription
                    self?.isProcessing = false
                }
            }
        }
    }
}
