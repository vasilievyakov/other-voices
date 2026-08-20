import SwiftUI

struct TranscriptView: View {
    let transcript: String
    var segments: [TranscriptSegment]? = nil
    /// Owner-set label -> name mapping; applied at display time only,
    /// the stored transcript text is never rewritten.
    var speakerNames: [String: String] = [:]
    var onSeek: ((Double) -> Void)? = nil
    /// Called with (label, name) when the owner renames a speaker.
    /// Empty name means "remove the rename".
    var onRename: ((String, String) -> Void)? = nil
    @State private var showCopied = false
    @State private var renameSegmentID: Double? = nil
    @State private var nameDraft = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Transcript", systemImage: "text.alignleft")
                    .font(.title3)
                    .fontWeight(.semibold)
                Spacer()

                if showCopied {
                    Label("Copied", systemImage: "checkmark.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.green)
                        .transition(.opacity)
                }

                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(transcript, forType: .string)
                    withAnimation(.easeInOut(duration: 0.3)) {
                        showCopied = true
                    }
                    AccessibilityNotification.Announcement("Transcript copied to clipboard").post()
                    Task {
                        try? await Task.sleep(for: .seconds(2))
                        withAnimation(.easeInOut(duration: 0.3)) {
                            showCopied = false
                        }
                    }
                } label: {
                    Label("Copy", systemImage: "doc.on.doc")
                        .font(.caption)
                }
                .buttonStyle(.borderless)
                .help("Copy transcript to clipboard")
            }

            if let segments = segments, !segments.isEmpty {
                segmentedView(segments)
            } else {
                plainView
            }
        }
    }

    private var plainView: some View {
        Text(SpeakerDisplay.substitute(transcript, names: speakerNames))
            .font(.system(.body, design: .monospaced))
            .textSelection(.enabled)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
    }

    private func segmentedView(_ segments: [TranscriptSegment]) -> some View {
        LazyVStack(alignment: .leading, spacing: 2) {
            ForEach(segments) { segment in
                HStack(alignment: .top, spacing: 8) {
                    Button {
                        onSeek?(segment.start)
                    } label: {
                        Text(segment.startFormatted)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(Color.accentColor)
                            .frame(minWidth: 40, alignment: .trailing)
                    }
                    .buttonStyle(.borderless)
                    .help("Jump to \(segment.startFormatted)")
                    .accessibilityLabel("Jump to \(segment.startFormatted)")

                    VStack(alignment: .leading, spacing: 1) {
                        if let label = segment.speaker {
                            speakerButton(segment, label: label)
                        }
                        Text(segment.text)
                            .font(.system(.body, design: .monospaced))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(.vertical, 3)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
    }

    // MARK: - Speaker rename

    private func speakerButton(_ segment: TranscriptSegment, label: String) -> some View {
        Button {
            nameDraft = speakerNames[label] ?? ""
            renameSegmentID = segment.id
        } label: {
            Text(SpeakerDisplay.displayName(for: label, names: speakerNames))
                .font(.system(.caption, design: .monospaced))
                .fontWeight(.semibold)
                .foregroundStyle(label == "SPEAKER_ME" ? Color.accentColor : Color.secondary)
        }
        .buttonStyle(.borderless)
        .help("Назвать спикера")
        .accessibilityLabel("Назвать спикера \(label)")
        .popover(
            isPresented: Binding(
                get: { renameSegmentID == segment.id },
                set: { if !$0 { renameSegmentID = nil } }
            ),
            arrowEdge: .bottom
        ) {
            renamePopover(label: label)
        }
    }

    private func renamePopover(label: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("Имя", text: $nameDraft)
                .textFieldStyle(.roundedBorder)
                .frame(width: 220)
                .onSubmit { commitRename(label) }
            HStack {
                if !(speakerNames[label] ?? "").isEmpty {
                    Button("Убрать имя") {
                        nameDraft = ""
                        commitRename(label)
                    }
                }
                Spacer()
                Button("Сохранить") { commitRename(label) }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(12)
    }

    private func commitRename(_ label: String) {
        onRename?(label, nameDraft.trimmingCharacters(in: .whitespacesAndNewlines))
        renameSegmentID = nil
    }
}
