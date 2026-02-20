import Foundation

/// User preferences for controlling daemon behavior (autonomy slider).
/// Simple toggles use @AppStorage directly in SettingsView.
/// This model is used for JSON export to ~/call-recorder/data/settings.json
/// so the Python daemon can read preferences.
package struct UserSettings: Codable, Equatable {

    // MARK: - Recording

    package var autoRecordCalls: Bool = true
    package var enabledApps: [String: Bool] = [
        "Zoom": true,
        "Google Meet": true,
        "Microsoft Teams": true,
        "Discord": true,
        "Telegram": true,
        "FaceTime": true,
    ]
    package var minCallDurationSeconds: Int = 30

    // MARK: - Processing

    package var transcribeCalls: Bool = true
    package var generateSummary: Bool = true
    package var extractCommitments: Bool = true
    package var defaultTemplate: String = "default"

    // MARK: - AI Model

    package var ollamaModel: String = "qwen3:14b"
    package var ollamaURL: String = "http://localhost:11434"

    // MARK: - Storage

    package var audioRetention: AudioRetention = .forever

    // MARK: - Types

    package enum AudioRetention: String, Codable, CaseIterable, Equatable {
        case forever = "forever"
        case days30 = "30_days"
        case days90 = "90_days"
        case year1 = "1_year"

        package var displayName: String {
            switch self {
            case .forever: return "Keep forever"
            case .days30: return "30 days"
            case .days90: return "90 days"
            case .year1: return "1 year"
            }
        }

        package var days: Int? {
            switch self {
            case .forever: return nil
            case .days30: return 30
            case .days90: return 90
            case .year1: return 365
            }
        }
    }

    // MARK: - Coding Keys (snake_case for Python)

    enum CodingKeys: String, CodingKey {
        case autoRecordCalls = "auto_record_calls"
        case enabledApps = "enabled_apps"
        case minCallDurationSeconds = "min_call_duration_seconds"
        case transcribeCalls = "transcribe_calls"
        case generateSummary = "generate_summary"
        case extractCommitments = "extract_commitments"
        case defaultTemplate = "default_template"
        case ollamaModel = "ollama_model"
        case ollamaURL = "ollama_url"
        case audioRetention = "audio_retention"
    }

    // MARK: - Supported Apps

    package static let supportedApps: [(key: String, displayName: String, icon: String)] = [
        ("Zoom", "Zoom", "video.fill"),
        ("Google Meet", "Google Meet", "globe"),
        ("Microsoft Teams", "Microsoft Teams", "person.3.fill"),
        ("Discord", "Discord", "headphones"),
        ("Telegram", "Telegram", "paperplane.fill"),
        ("FaceTime", "FaceTime", "phone.fill"),
    ]

    // MARK: - Defaults

    package static let `default` = UserSettings()
}
