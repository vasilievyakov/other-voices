import Foundation
import OSLog

private let logger = Logger(subsystem: "com.user.other-voices", category: "resummarize")

@MainActor
@Observable
final class ResummarizeService {
    var isProcessing = false
    var error: String?

    func resummarize(sessionId: String, templateName: String) async {
        guard !isProcessing else { return }
        isProcessing = true
        error = nil

        let pythonPath = NSHomeDirectory() + "/call-recorder/.venv/bin/python"
        let scriptPath = NSHomeDirectory() + "/call-recorder/resummarize.py"
        let workDir = NSHomeDirectory() + "/call-recorder"

        let result: (output: String, status: Int32)? = await Task.detached {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [scriptPath, "--session", sessionId, "--template", templateName]
            process.currentDirectoryURL = URL(fileURLWithPath: workDir)

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            do {
                try process.run()
                process.waitUntilExit()

                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8) ?? ""
                return (output, process.terminationStatus)
            } catch {
                let desc = error.localizedDescription
                logger.error("Process launch failed: \(desc)")
                return (desc, -1)
            }
        }.value

        if let result {
            if result.status == 0 {
                logger.info("Re-summarize OK: \(result.output)")
                error = nil
            } else if result.status == -1 {
                error = result.output
            } else {
                logger.error("Re-summarize failed: \(result.output)")
                error = "Re-summarization failed"
            }
        }
        isProcessing = false
    }
}
