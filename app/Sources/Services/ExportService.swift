import Foundation
#if canImport(AppKit)
import AppKit
import UniformTypeIdentifiers
#endif

package enum ExportService {

    // MARK: - Markdown Export

    package static func exportAsMarkdown(call: Call, commitments: [Commitment]) -> String {
        var lines: [String] = []

        // Title
        let title = call.callTitle ?? "\(call.appName) Call"
        let dateStr = Call.dateFormatter.string(from: call.startedAt)
        lines.append("# \(title) — \(dateStr)")
        lines.append("")

        // Metadata
        lines.append("**Duration:** \(call.durationFormatted)")
        if let template = call.templateName {
            lines.append("**Template:** \(template)")
        }
        lines.append("**App:** \(call.appName)")
        lines.append("")

        // Summary
        if let summary = call.summary {
            lines.append("## Summary")
            lines.append("")

            if let text = summary.summary {
                lines.append(text)
                lines.append("")
            }

            if let participants = summary.participants, !participants.isEmpty {
                lines.append("### Participants")
                for p in participants {
                    lines.append("- \(p)")
                }
                lines.append("")
            }

            if let keyPoints = summary.keyPoints, !keyPoints.isEmpty {
                lines.append("### Key Points")
                for point in keyPoints {
                    lines.append("- \(point)")
                }
                lines.append("")
            }

            if let decisions = summary.decisions, !decisions.isEmpty {
                lines.append("### Decisions")
                for decision in decisions {
                    lines.append("- \(decision)")
                }
                lines.append("")
            }

            if let actionItems = summary.actionItems, !actionItems.isEmpty {
                lines.append("### Action Items")
                for item in actionItems {
                    lines.append("- \(item)")
                }
                lines.append("")
            }

            if let entities = summary.entities, !entities.isEmpty {
                lines.append("### Entities")
                for entity in entities {
                    lines.append("- \(entity.name) (\(entity.type))")
                }
                lines.append("")
            }

            // Additional sections
            for (sectionTitle, items) in summary.additionalSections.sorted(by: { $0.key < $1.key }) {
                lines.append("### \(sectionTitle)")
                for item in items {
                    lines.append("- \(item)")
                }
                lines.append("")
            }
        }

        // Commitments
        if !commitments.isEmpty {
            lines.append("## Commitments")
            lines.append("")
            for c in commitments {
                var entry = "- [\(c.direction)] \(c.text)"
                if let deadline = c.deadlineRaw {
                    entry += " (deadline: \(deadline))"
                }
                if c.status != "open" {
                    entry += " — *\(c.status)*"
                }
                lines.append(entry)
            }
            lines.append("")
        }

        // Notes
        if let notes = call.notes, !notes.isEmpty {
            lines.append("## Notes")
            lines.append("")
            lines.append(notes)
            lines.append("")
        }

        // Transcript
        if let segments = call.transcriptSegments, !segments.isEmpty {
            lines.append("## Transcript")
            lines.append("")
            for segment in segments {
                lines.append("**[\(segment.startFormatted)]** \(segment.text)")
            }
            lines.append("")
        } else if let transcript = call.transcript, !transcript.isEmpty {
            lines.append("## Transcript")
            lines.append("")
            lines.append(transcript)
            lines.append("")
        }

        return lines.joined(separator: "\n")
    }

    // MARK: - Plain Text Export

    package static func exportAsText(call: Call, commitments: [Commitment]) -> String {
        var lines: [String] = []

        // Title
        let title = call.callTitle ?? "\(call.appName) Call"
        let dateStr = Call.dateFormatter.string(from: call.startedAt)
        lines.append("\(title) — \(dateStr)")
        lines.append(String(repeating: "=", count: min(title.count + dateStr.count + 3, 60)))
        lines.append("")

        // Metadata
        lines.append("Duration: \(call.durationFormatted)")
        if let template = call.templateName {
            lines.append("Template: \(template)")
        }
        lines.append("App: \(call.appName)")
        lines.append("")

        // Summary
        if let summary = call.summary {
            lines.append("SUMMARY")
            lines.append(String(repeating: "-", count: 7))

            if let text = summary.summary {
                lines.append(text)
                lines.append("")
            }

            if let participants = summary.participants, !participants.isEmpty {
                lines.append("Participants:")
                for p in participants {
                    lines.append("  - \(p)")
                }
                lines.append("")
            }

            if let keyPoints = summary.keyPoints, !keyPoints.isEmpty {
                lines.append("Key Points:")
                for point in keyPoints {
                    lines.append("  - \(point)")
                }
                lines.append("")
            }

            if let decisions = summary.decisions, !decisions.isEmpty {
                lines.append("Decisions:")
                for decision in decisions {
                    lines.append("  - \(decision)")
                }
                lines.append("")
            }

            if let actionItems = summary.actionItems, !actionItems.isEmpty {
                lines.append("Action Items:")
                for item in actionItems {
                    lines.append("  - \(item)")
                }
                lines.append("")
            }

            if let entities = summary.entities, !entities.isEmpty {
                lines.append("Entities:")
                for entity in entities {
                    lines.append("  - \(entity.name) (\(entity.type))")
                }
                lines.append("")
            }

            for (sectionTitle, items) in summary.additionalSections.sorted(by: { $0.key < $1.key }) {
                lines.append("\(sectionTitle):")
                for item in items {
                    lines.append("  - \(item)")
                }
                lines.append("")
            }
        }

        // Commitments
        if !commitments.isEmpty {
            lines.append("COMMITMENTS")
            lines.append(String(repeating: "-", count: 11))
            for c in commitments {
                var entry = "  [\(c.direction)] \(c.text)"
                if let deadline = c.deadlineRaw {
                    entry += " (deadline: \(deadline))"
                }
                if c.status != "open" {
                    entry += " — \(c.status)"
                }
                lines.append(entry)
            }
            lines.append("")
        }

        // Notes
        if let notes = call.notes, !notes.isEmpty {
            lines.append("NOTES")
            lines.append(String(repeating: "-", count: 5))
            lines.append(notes)
            lines.append("")
        }

        // Transcript
        if let segments = call.transcriptSegments, !segments.isEmpty {
            lines.append("TRANSCRIPT")
            lines.append(String(repeating: "-", count: 10))
            for segment in segments {
                lines.append("[\(segment.startFormatted)] \(segment.text)")
            }
            lines.append("")
        } else if let transcript = call.transcript, !transcript.isEmpty {
            lines.append("TRANSCRIPT")
            lines.append(String(repeating: "-", count: 10))
            lines.append(transcript)
            lines.append("")
        }

        return lines.joined(separator: "\n")
    }

    // MARK: - Save to File (NSSavePanel)

    #if canImport(AppKit)
    @MainActor
    package static func saveMarkdownFile(call: Call, commitments: [Commitment]) {
        let content = exportAsMarkdown(call: call, commitments: commitments)
        let dateStr = formatDateForFilename(call.startedAt)
        let safeName = call.appName.replacingOccurrences(of: " ", with: "-").lowercased()
        let defaultName = "call-\(safeName)-\(dateStr).md"

        let panel = NSSavePanel()
        panel.title = "Save Call Export"
        panel.nameFieldStringValue = defaultName
        panel.allowedContentTypes = [UTType(filenameExtension: "md") ?? .plainText]
        panel.canCreateDirectories = true

        guard panel.runModal() == .OK, let url = panel.url else { return }

        do {
            try content.write(to: url, atomically: true, encoding: .utf8)
        } catch {
            let alert = NSAlert()
            alert.messageText = "Export Failed"
            alert.informativeText = error.localizedDescription
            alert.alertStyle = .warning
            alert.runModal()
        }
    }
    #endif

    // MARK: - Copy to Clipboard

    #if canImport(AppKit)
    package static func copyToClipboard(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
    #endif

    // MARK: - Helpers

    private static func formatDateForFilename(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }
}
