import SwiftUI

struct ChatView: View {
    let sessionId: String
    @State private var chatService = ChatService()
    @State private var inputText = ""
    @State private var showClearConfirmation = false
    @State private var processingStart: Date?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Chat", systemImage: "bubble.left.and.bubble.right")
                    .font(.title3)
                    .fontWeight(.semibold)
                Spacer()
                if !chatService.messages.isEmpty {
                    Button {
                        showClearConfirmation = true
                    } label: {
                        Label("Clear", systemImage: "trash")
                            .font(.caption)
                    }
                    .buttonStyle(.borderless)
                    .help("Clear chat history")
                    .confirmationDialog("Clear chat history?",
                        isPresented: $showClearConfirmation,
                        titleVisibility: .visible
                    ) {
                        Button("Clear", role: .destructive) {
                            chatService.clear()
                        }
                        Button("Cancel", role: .cancel) {}
                    } message: {
                        Text("This will delete all messages for this call's chat.")
                    }
                }
            }

            if chatService.messages.isEmpty && !chatService.isProcessing {
                VStack(spacing: 8) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.largeTitle)
                        .foregroundStyle(.secondary)
                    Text("Ask questions about this call")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Try: \"What were the key decisions?\" or \"Summarize the action items\"")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 24)
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(chatService.messages) { msg in
                                messageBubble(msg)
                                    .id(msg.id)
                            }
                        }
                    }
                    .frame(maxHeight: 500)
                    .onChange(of: chatService.messages.count) { _, _ in
                        if let last = chatService.messages.last {
                            withAnimation(.easeOut(duration: 0.2)) {
                                proxy.scrollTo(last.id, anchor: .bottom)
                            }
                        }
                    }
                }
            }

            if let error = chatService.error {
                Text(sanitizeError(error))
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            if chatService.isProcessing, let start = processingStart {
                let elapsed = Date().timeIntervalSince(start)
                if elapsed > 30 {
                    Text("Taking longer than expected...")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }

            HStack(spacing: 8) {
                TextField("Ask a question...", text: $inputText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { sendMessage() }

                if chatService.isProcessing {
                    Button {
                        chatService.cancel()
                        processingStart = nil
                    } label: {
                        Image(systemName: "stop.circle.fill")
                            .foregroundStyle(.red)
                    }
                    .buttonStyle(.borderless)
                    .help("Cancel")
                    .accessibilityLabel("Cancel AI response")
                } else {
                    Button {
                        sendMessage()
                    } label: {
                        Image(systemName: "paperplane.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty)
                    .help("Send message")
                }
            }
        }
    }

    private func sendMessage() {
        let question = inputText.trimmingCharacters(in: .whitespaces)
        guard !question.isEmpty else { return }
        inputText = ""
        processingStart = Date()
        chatService.send(question: question, sessionId: sessionId)
    }

    private func messageBubble(_ msg: ChatMessage) -> some View {
        HStack {
            if msg.isUser { Spacer(minLength: 40) }

            Text(msg.content)
                .font(.body)
                .padding(10)
                .background(
                    msg.isUser
                        ? Color.accentColor.opacity(0.15)
                        : Color.secondary.opacity(0.15),
                    in: RoundedRectangle(cornerRadius: 10)
                )
                .textSelection(.enabled)
                .accessibilityLabel("\(msg.isUser ? "You" : "AI"): \(msg.content)")

            if msg.isAssistant { Spacer(minLength: 40) }
        }
    }

    private func sanitizeError(_ error: String) -> String {
        // Remove stack traces and internal details
        if error.contains("Traceback") || error.contains("File \"") {
            return "An error occurred while processing your question. Please try again."
        }
        // Truncate long errors
        if error.count > 200 {
            return String(error.prefix(200)) + "..."
        }
        return error
    }
}
