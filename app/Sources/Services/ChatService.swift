import Foundation
import OSLog

private let logger = Logger(subsystem: "com.user.other-voices", category: "chat")

@Observable
final class ChatService {
    var messages: [ChatMessage] = []
    var isProcessing = false
    var error: String?

    private let basePath: String
    private var currentProcess: Process?

    init() {
        self.basePath = NSHomeDirectory() + "/call-recorder"
    }

    func cancel() {
        currentProcess?.terminate()
        currentProcess = nil
        isProcessing = false
        error = nil
    }

    func send(question: String, sessionId: String) {
        guard !isProcessing else { return }
        isProcessing = true
        error = nil

        // Add user message immediately
        let userMsg = ChatMessage(role: "user", content: question)
        messages.append(userMsg)

        Task.detached { [weak self, basePath] in
            let venvPython = basePath + "/.venv/bin/python"
            let chatCli = basePath + "/chat_cli.py"

            let process = Process()
            process.executableURL = URL(fileURLWithPath: venvPython)
            process.arguments = [chatCli, sessionId, question]
            process.currentDirectoryURL = URL(fileURLWithPath: basePath)

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            do {
                await MainActor.run {
                    self?.currentProcess = process
                }
                try process.run()
                process.waitUntilExit()

                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

                await MainActor.run {
                    if process.terminationStatus == 0 && !output.isEmpty {
                        let assistantMsg = ChatMessage(role: "assistant", content: output)
                        self?.messages.append(assistantMsg)
                    } else {
                        self?.error = output.isEmpty ? "No response" : output
                    }
                    self?.isProcessing = false
                }
            } catch {
                logger.error("Chat process failed: \(error.localizedDescription)")
                await MainActor.run {
                    self?.error = error.localizedDescription
                    self?.isProcessing = false
                }
            }
        }
    }

    func clear() {
        messages.removeAll()
        error = nil
    }
}
