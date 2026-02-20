import SwiftUI

struct ChatView: View {
    let sessionId: String
    @State private var chatService = ChatService()
    @State private var inputText = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Chat")
                    .font(.headline)
                    .fontWeight(.bold)
                Spacer()
                if !chatService.messages.isEmpty {
                    Button {
                        chatService.clear()
                    } label: {
                        Label("Clear", systemImage: "trash")
                            .font(.caption)
                    }
                    .buttonStyle(.borderless)
                }
            }

            if chatService.messages.isEmpty {
                Text("Ask questions about this call")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 20)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(chatService.messages) { msg in
                            messageBubble(msg)
                        }
                    }
                }
                .frame(maxHeight: 300)
            }

            if let error = chatService.error {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            HStack(spacing: 8) {
                TextField("Ask a question...", text: $inputText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { sendMessage() }

                Button {
                    sendMessage()
                } label: {
                    if chatService.isProcessing {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: "paperplane.fill")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty || chatService.isProcessing)
            }
        }
    }

    private func sendMessage() {
        let question = inputText.trimmingCharacters(in: .whitespaces)
        guard !question.isEmpty else { return }
        inputText = ""
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
                        : Color.secondary.opacity(0.1),
                    in: RoundedRectangle(cornerRadius: 10)
                )
                .textSelection(.enabled)

            if msg.isAssistant { Spacer(minLength: 40) }
        }
    }
}
