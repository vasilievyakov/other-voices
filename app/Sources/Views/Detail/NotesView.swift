import SwiftUI

struct NotesView: View {
    let sessionId: String
    @State private var notesText: String
    @State private var saveTask: Task<Void, Never>?

    private let db: SQLiteDatabase

    init(sessionId: String, initialNotes: String?) {
        self.sessionId = sessionId
        self._notesText = State(initialValue: initialNotes ?? "")
        let dbPath = NSHomeDirectory() + "/call-recorder/data/calls.db"
        self.db = SQLiteDatabase(path: dbPath)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Notes")
                    .font(.headline)
                    .fontWeight(.bold)
                Spacer()
            }

            TextEditor(text: $notesText)
                .font(.body)
                .frame(minHeight: 80, maxHeight: 200)
                .padding(8)
                .background(Color(nsColor: .controlBackgroundColor))
                .cornerRadius(8)
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
                )
                .onChange(of: notesText) {
                    debounceSave()
                }
        }
    }

    private func debounceSave() {
        saveTask?.cancel()
        saveTask = Task {
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            let text = notesText.isEmpty ? nil : notesText
            db.updateNotes(sessionId: sessionId, notes: text)
        }
    }
}
