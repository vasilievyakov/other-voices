import SwiftUI

struct NotesView: View {
    let sessionId: String
    @State private var notesText: String
    @State private var saveTask: Task<Void, Never>?
    @State private var showSaved = false

    private let db: SQLiteDatabase

    init(sessionId: String, initialNotes: String?) {
        self.sessionId = sessionId
        self._notesText = State(initialValue: initialNotes ?? "")
        let dbPath = NSHomeDirectory() + "/call-recorder/data/calls.db"
        self.db = SQLiteDatabase(path: dbPath)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Notes", systemImage: "note.text")
                    .font(.title3)
                    .fontWeight(.semibold)
                Spacer()
                if showSaved {
                    Label("Saved", systemImage: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.green)
                        .transition(.opacity)
                }
            }

            ZStack(alignment: .topLeading) {
                TextEditor(text: $notesText)
                    .font(.body)
                    .frame(minHeight: 80, maxHeight: 200)
                    .padding(8)
                    .scrollContentBackground(.hidden)
                    .background(.background.secondary)
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .strokeBorder(.separator, lineWidth: 0.5)
                    )
                    .accessibilityLabel("Notes")
                    .onChange(of: notesText) {
                        debounceSave()
                    }

                if notesText.isEmpty {
                    Text("Add notes for this call...")
                        .font(.body)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 16)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
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

            withAnimation(.easeInOut(duration: 0.3)) {
                showSaved = true
            }
            AccessibilityNotification.Announcement("Notes saved").post()
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            withAnimation(.easeInOut(duration: 0.3)) {
                showSaved = false
            }
        }
    }
}
