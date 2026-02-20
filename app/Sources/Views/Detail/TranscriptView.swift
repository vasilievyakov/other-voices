import SwiftUI

struct TranscriptView: View {
    let transcript: String
    var segments: [TranscriptSegment]? = nil
    var onSeek: ((Double) -> Void)? = nil
    @State private var showCopied = false

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
        Text(transcript)
            .font(.system(.body, design: .monospaced))
            .textSelection(.enabled)
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
    }

    private func segmentedView(_ segments: [TranscriptSegment]) -> some View {
        VStack(alignment: .leading, spacing: 2) {
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

                    Text(segment.text)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.vertical, 3)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
    }
}
