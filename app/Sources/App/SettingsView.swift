import OtherVoicesLib
import SwiftUI

struct SettingsView: View {
    var body: some View {
        TabView {
            RecordingSettingsView()
                .tabItem {
                    Label("Recording", systemImage: "record.circle")
                }

            ProcessingSettingsView()
                .tabItem {
                    Label("Processing", systemImage: "cpu")
                }

            AIModelSettingsView()
                .tabItem {
                    Label("AI Model", systemImage: "brain")
                }

            StorageSettingsView()
                .tabItem {
                    Label("Storage", systemImage: "externaldrive")
                }
        }
        .frame(width: 520, height: 460)
    }
}

// MARK: - Recording Settings

struct RecordingSettingsView: View {
    @AppStorage("autoRecordCalls") private var autoRecordCalls = true
    @AppStorage("minCallDurationSeconds") private var minCallDuration = 30
    @AppStorage("enableZoom") private var enableZoom = true
    @AppStorage("enableGoogleMeet") private var enableGoogleMeet = true
    @AppStorage("enableMicrosoftTeams") private var enableMicrosoftTeams = true
    @AppStorage("enableDiscord") private var enableDiscord = true
    @AppStorage("enableTelegram") private var enableTelegram = true
    @AppStorage("enableFaceTime") private var enableFaceTime = true

    var body: some View {
        Form {
            Section {
                Toggle("Auto-record calls", isOn: $autoRecordCalls)
                    .toggleStyle(.switch)
            } footer: {
                Text("When enabled, the daemon automatically records detected calls.")
                    .foregroundStyle(.secondary)
            }

            Section {
                Toggle(isOn: $enableZoom) {
                    Label("Zoom", systemImage: "video.fill")
                }
                Toggle(isOn: $enableGoogleMeet) {
                    Label("Google Meet", systemImage: "globe")
                }
                Toggle(isOn: $enableMicrosoftTeams) {
                    Label("Microsoft Teams", systemImage: "person.3.fill")
                }
                Toggle(isOn: $enableDiscord) {
                    Label("Discord", systemImage: "headphones")
                }
                Toggle(isOn: $enableTelegram) {
                    Label("Telegram", systemImage: "paperplane.fill")
                }
                Toggle(isOn: $enableFaceTime) {
                    Label("FaceTime", systemImage: "phone.fill")
                }
            } header: {
                Text("Applications")
            }
            .disabled(!autoRecordCalls)

            Section {
                HStack {
                    Text("Minimum call duration")
                    Spacer()
                    Text("\(minCallDuration)s")
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                Slider(
                    value: Binding(
                        get: { Double(minCallDuration) },
                        set: { minCallDuration = Int($0) }
                    ),
                    in: 10...300,
                    step: 10
                )
            } footer: {
                Text("Calls shorter than this will be ignored. Default: 30 seconds.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .onChange(of: autoRecordCalls) { _, _ in syncSettings() }
        .onChange(of: minCallDuration) { _, _ in syncSettings() }
        .onChange(of: enableZoom) { _, _ in syncSettings() }
        .onChange(of: enableGoogleMeet) { _, _ in syncSettings() }
        .onChange(of: enableMicrosoftTeams) { _, _ in syncSettings() }
        .onChange(of: enableDiscord) { _, _ in syncSettings() }
        .onChange(of: enableTelegram) { _, _ in syncSettings() }
        .onChange(of: enableFaceTime) { _, _ in syncSettings() }
        .onAppear { syncSettings() }
    }

    private func syncSettings() {
        var settings = SettingsSync.shared.load()
        settings.autoRecordCalls = autoRecordCalls
        settings.minCallDurationSeconds = minCallDuration
        settings.enabledApps = [
            "Zoom": enableZoom,
            "Google Meet": enableGoogleMeet,
            "Microsoft Teams": enableMicrosoftTeams,
            "Discord": enableDiscord,
            "Telegram": enableTelegram,
            "FaceTime": enableFaceTime,
        ]
        SettingsSync.shared.save(settings)
    }
}

// MARK: - Processing Settings

struct ProcessingSettingsView: View {
    @AppStorage("transcribeCalls") private var transcribeCalls = true
    @AppStorage("generateSummary") private var generateSummary = true
    @AppStorage("extractCommitments") private var extractCommitments = true
    @AppStorage("defaultTemplate") private var defaultTemplate = "default"

    private let templates = Template.loadFromJSON()

    var body: some View {
        Form {
            Section {
                Toggle("Transcribe calls", isOn: $transcribeCalls)
                    .toggleStyle(.switch)

                Toggle("Generate AI summary", isOn: $generateSummary)
                    .toggleStyle(.switch)
                    .disabled(!transcribeCalls)

                Toggle("Extract commitments", isOn: $extractCommitments)
                    .toggleStyle(.switch)
                    .disabled(!transcribeCalls)
            } header: {
                Text("Pipeline")
            } footer: {
                if !transcribeCalls {
                    Text("Transcription is required for summary and commitment extraction.")
                        .foregroundStyle(.orange)
                } else {
                    Text("Control which processing steps run after recording ends.")
                        .foregroundStyle(.secondary)
                }
            }

            Section {
                Picker("Template", selection: $defaultTemplate) {
                    ForEach(templates) { template in
                        Text(template.displayName)
                            .tag(template.name)
                    }
                }
                .pickerStyle(.menu)

                if let selected = templates.first(where: { $0.name == defaultTemplate }) {
                    Text(selected.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Default Template")
            }
        }
        .formStyle(.grouped)
        .onChange(of: transcribeCalls) { _, newValue in
            if !newValue {
                generateSummary = false
                extractCommitments = false
            }
            syncSettings()
        }
        .onChange(of: generateSummary) { _, _ in syncSettings() }
        .onChange(of: extractCommitments) { _, _ in syncSettings() }
        .onChange(of: defaultTemplate) { _, _ in syncSettings() }
        .onAppear { syncSettings() }
    }

    private func syncSettings() {
        var settings = SettingsSync.shared.load()
        settings.transcribeCalls = transcribeCalls
        settings.generateSummary = generateSummary
        settings.extractCommitments = extractCommitments
        settings.defaultTemplate = defaultTemplate
        SettingsSync.shared.save(settings)
    }
}

// MARK: - AI Model Settings

struct AIModelSettingsView: View {
    @AppStorage("ollamaModel") private var ollamaModel = "qwen3:14b"
    @AppStorage("ollamaURL") private var ollamaURL = "http://localhost:11434"
    @State private var ollamaStatus: OllamaStatus = .unknown
    @State private var checkTask: Task<Void, Never>?

    var body: some View {
        Form {
            Section {
                HStack {
                    Text("Model")
                    Spacer()
                    TextField("Model name", text: $ollamaModel)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 200)
                        .multilineTextAlignment(.trailing)
                }

                HStack {
                    Text("URL")
                    Spacer()
                    TextField("Ollama URL", text: $ollamaURL)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 280)
                        .multilineTextAlignment(.trailing)
                }
            } header: {
                Text("Ollama")
            }

            Section {
                HStack {
                    statusIcon
                    Text(ollamaStatus.label)
                        .foregroundStyle(statusColor)
                    Spacer()
                    Button("Check") {
                        checkConnection()
                    }
                }

                if case .connected(let models) = ollamaStatus {
                    let modelBase = ollamaModel.split(separator: ":").first.map(String.init) ?? ollamaModel
                    if models.contains(where: { $0.hasPrefix(modelBase) }) {
                        Label("Model \"\(ollamaModel)\" is available", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                            .font(.caption)
                    } else if !models.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            Label("Model \"\(ollamaModel)\" not found", systemImage: "exclamationmark.triangle.fill")
                                .foregroundStyle(.orange)
                                .font(.caption)
                            Text("Available: \(models.prefix(5).joined(separator: ", "))")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            } header: {
                Text("Connection Status")
            }
        }
        .formStyle(.grouped)
        .onAppear { checkConnection() }
        .onChange(of: ollamaModel) { _, _ in syncSettings() }
        .onChange(of: ollamaURL) { _, _ in
            syncSettings()
            checkConnection()
        }
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch ollamaStatus {
        case .connected:
            Image(systemName: "circle.fill")
                .foregroundStyle(.green)
                .font(.caption2)
        case .checking:
            ProgressView()
                .controlSize(.small)
        case .unavailable, .error:
            Image(systemName: "circle.fill")
                .foregroundStyle(.red)
                .font(.caption2)
        case .unknown:
            Image(systemName: "circle.fill")
                .foregroundStyle(.gray)
                .font(.caption2)
        }
    }

    private var statusColor: Color {
        switch ollamaStatus {
        case .connected: return .primary
        case .unavailable, .error: return .red
        default: return .secondary
        }
    }

    private func checkConnection() {
        checkTask?.cancel()
        ollamaStatus = .checking
        checkTask = Task {
            let status = await SettingsSync.shared.checkOllama(url: ollamaURL)
            if !Task.isCancelled {
                ollamaStatus = status
            }
        }
    }

    private func syncSettings() {
        var settings = SettingsSync.shared.load()
        settings.ollamaModel = ollamaModel
        settings.ollamaURL = ollamaURL
        SettingsSync.shared.save(settings)
    }
}

// MARK: - Storage Settings

struct StorageSettingsView: View {
    @AppStorage("audioRetention") private var audioRetention = "forever"
    @State private var storageInfo: StorageInfo?

    var body: some View {
        Form {
            Section {
                if let info = storageInfo {
                    LabeledContent("Directory") {
                        HStack {
                            Text(info.dataDirectory)
                                .font(.system(.body, design: .monospaced))
                                .textSelection(.enabled)
                            Button {
                                NSWorkspace.shared.selectFile(
                                    nil,
                                    inFileViewerRootedAtPath: info.dataDirectory
                                )
                            } label: {
                                Image(systemName: "folder")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                } else {
                    Text("Loading...")
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Data Location")
            }

            Section {
                if let info = storageInfo {
                    LabeledContent("Recordings") {
                        Text(info.formattedRecordings)
                            .monospacedDigit()
                    }
                    LabeledContent("Database") {
                        Text(info.formattedDatabase)
                            .monospacedDigit()
                    }
                    LabeledContent("Total") {
                        Text(info.formattedTotal)
                            .monospacedDigit()
                            .fontWeight(.medium)
                    }
                } else {
                    Text("Calculating...")
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Usage")
            }

            Section {
                Picker("Audio retention", selection: $audioRetention) {
                    ForEach(UserSettings.AudioRetention.allCases, id: \.rawValue) { retention in
                        Text(retention.displayName)
                            .tag(retention.rawValue)
                    }
                }
                .pickerStyle(.menu)
            } header: {
                Text("Retention")
            } footer: {
                Text("Old recordings will be deleted after the retention period. Transcripts and summaries are kept permanently.")
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .onAppear { loadStorageInfo() }
        .onChange(of: audioRetention) { _, _ in syncSettings() }
    }

    private func loadStorageInfo() {
        storageInfo = SettingsSync.shared.storageInfo()
    }

    private func syncSettings() {
        var settings = SettingsSync.shared.load()
        settings.audioRetention = UserSettings.AudioRetention(rawValue: audioRetention) ?? .forever
        SettingsSync.shared.save(settings)
    }
}
