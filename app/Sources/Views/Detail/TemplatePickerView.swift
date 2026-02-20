import SwiftUI

struct TemplatePickerView: View {
    let sessionId: String
    let currentTemplate: String?
    let onResummarize: () -> Void

    @State private var templates = Template.loadFromJSON()
    @State private var selectedTemplate: String = "default"
    @State private var resummarizeService = ResummarizeService()
    @Environment(\.dismiss) private var dismiss

    init(sessionId: String, currentTemplate: String?, onResummarize: @escaping () -> Void) {
        self.sessionId = sessionId
        self.currentTemplate = currentTemplate
        self.onResummarize = onResummarize
        self._selectedTemplate = State(initialValue: currentTemplate ?? "default")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Choose Template", systemImage: "doc.text")
                .font(.title3)
                .fontWeight(.semibold)

            Text("This will re-generate the summary using the selected template.")
                .font(.caption)
                .foregroundStyle(.secondary)

            ForEach(templates) { template in
                Button {
                    selectedTemplate = template.name
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(template.displayName)
                                .font(.body)
                                .fontWeight(selectedTemplate == template.name ? .semibold : .regular)
                            Text(template.description)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if selectedTemplate == template.name {
                            Image(systemName: "checkmark")
                                .foregroundStyle(.blue)
                                .accessibilityHidden(true)
                        }
                    }
                    .padding(.vertical, 4)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selectedTemplate == template.name ? .isSelected : [])
            }

            Divider()

            HStack {
                if resummarizeService.isProcessing {
                    ProgressView()
                        .controlSize(.small)
                    Text("Re-summarizing...")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let error = resummarizeService.error {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                }

                Spacer()

                Button("Cancel") {
                    dismiss()
                }

                Button("Apply") {
                    Task {
                        await resummarizeService.resummarize(
                            sessionId: sessionId,
                            templateName: selectedTemplate
                        )
                        onResummarize()
                        dismiss()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(resummarizeService.isProcessing || selectedTemplate == currentTemplate)
            }
        }
        .padding()
        .frame(width: 360)
    }
}
