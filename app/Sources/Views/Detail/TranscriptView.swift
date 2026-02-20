import SwiftUI

struct TranscriptView: View {
    let transcript: String
    var segments: [TranscriptSegment]? = nil
    var onSeek: ((Double) -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Transcript")
                    .font(.headline)
                    .fontWeight(.bold)
                Spacer()

                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(transcript, forType: .string)
                } label: {
                    Label("Copy", systemImage: "doc.on.doc")
                        .font(.caption)
                }
                .buttonStyle(.borderless)
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
            .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 6))
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
                            .frame(width: 40, alignment: .trailing)
                    }
                    .buttonStyle(.borderless)

                    Text(segment.text)
                        .font(.system(.body, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.vertical, 3)
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 6))
    }
}
