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
            Text("Choose Template")
                .font(.headline)

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
                        }
                    }
                    .padding(.vertical, 4)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
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
                }

                Spacer()

                Button("Cancel") {
                    dismiss()
                }

                Button("Apply") {
                    resummarizeService.resummarize(
                        sessionId: sessionId,
                        templateName: selectedTemplate
                    ) {
                        onResummarize()
                        dismiss()
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(resummarizeService.isProcessing)
            }
        }
        .padding()
        .frame(width: 320)
    }
}
