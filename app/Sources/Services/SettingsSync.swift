import Foundation
import OSLog

private let logger = Logger(subsystem: "com.user.other-voices", category: "settings")

/// Syncs UserSettings to ~/call-recorder/data/settings.json so the Python daemon can read preferences.
/// Also provides Ollama connectivity check.
@MainActor
package final class SettingsSync {

    package static let shared = SettingsSync()

    private let settingsPath: String
    private let dataDir: String

    private init() {
        self.dataDir = NSHomeDirectory() + "/call-recorder/data"
        self.settingsPath = dataDir + "/settings.json"
    }

    // MARK: - Write settings.json

    /// Write settings to JSON file atomically. Called whenever a setting changes.
    package func save(_ settings: UserSettings) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

        do {
            let data = try encoder.encode(settings)
            let url = URL(fileURLWithPath: settingsPath)
            let tmpURL = url.deletingLastPathComponent().appendingPathComponent("settings.json.tmp")

            // Ensure data directory exists
            try FileManager.default.createDirectory(
                atPath: dataDir,
                withIntermediateDirectories: true
            )

            try data.write(to: tmpURL, options: .atomic)

            // Atomic replace using rename
            if FileManager.default.fileExists(atPath: settingsPath) {
                try FileManager.default.removeItem(atPath: settingsPath)
            }
            try FileManager.default.moveItem(atPath: tmpURL.path, toPath: settingsPath)

            logger.info("Settings saved to \(self.settingsPath)")
        } catch {
            logger.error("Failed to save settings: \(error)")
        }
    }

    // MARK: - Load settings.json

    /// Load settings from JSON file. Returns defaults if file doesn't exist.
    package func load() -> UserSettings {
        guard let data = FileManager.default.contents(atPath: settingsPath) else {
            return .default
        }
        return (try? JSONDecoder().decode(UserSettings.self, from: data)) ?? .default
    }

    // MARK: - Ollama connectivity check

    /// Check if Ollama is reachable at the given URL.
    package func checkOllama(url: String) async -> OllamaStatus {
        guard let baseURL = URL(string: url) else {
            return .error("Invalid URL")
        }
        let tagsURL = baseURL.appendingPathComponent("api/tags")
        var request = URLRequest(url: tagsURL)
        request.timeoutInterval = 5

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                return .error("HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)")
            }

            // Parse model list
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let models = json["models"] as? [[String: Any]] {
                let names = models.compactMap { $0["name"] as? String }
                return .connected(models: names)
            }
            return .connected(models: [])
        } catch {
            return .unavailable
        }
    }

    // MARK: - Storage info

    /// Calculate total storage used by recordings and database.
    package func storageInfo() -> StorageInfo {
        let fm = FileManager.default
        let recordingsDir = dataDir + "/recordings"
        let dbPath = dataDir + "/calls.db"

        var recordingsSize: UInt64 = 0
        var dbSize: UInt64 = 0

        // Database size
        if let attrs = try? fm.attributesOfItem(atPath: dbPath),
           let size = attrs[.size] as? UInt64 {
            dbSize = size
        }

        // Recordings directory size
        if let enumerator = fm.enumerator(atPath: recordingsDir) {
            while let file = enumerator.nextObject() as? String {
                let fullPath = recordingsDir + "/" + file
                if let attrs = try? fm.attributesOfItem(atPath: fullPath),
                   let size = attrs[.size] as? UInt64 {
                    recordingsSize += size
                }
            }
        }

        return StorageInfo(
            dataDirectory: dataDir,
            recordingsBytes: recordingsSize,
            databaseBytes: dbSize,
            totalBytes: recordingsSize + dbSize
        )
    }
}

// MARK: - Types

package enum OllamaStatus: Equatable {
    case unknown
    case checking
    case connected(models: [String])
    case unavailable
    case error(String)

    package var label: String {
        switch self {
        case .unknown: return "Not checked"
        case .checking: return "Checking..."
        case .connected(let models):
            return "Connected (\(models.count) models)"
        case .unavailable: return "Not available"
        case .error(let msg): return "Error: \(msg)"
        }
    }

    package var isConnected: Bool {
        if case .connected = self { return true }
        return false
    }
}

package struct StorageInfo: Equatable {
    package let dataDirectory: String
    package let recordingsBytes: UInt64
    package let databaseBytes: UInt64
    package let totalBytes: UInt64

    package var formattedTotal: String {
        ByteCountFormatter.string(fromByteCount: Int64(totalBytes), countStyle: .file)
    }

    package var formattedRecordings: String {
        ByteCountFormatter.string(fromByteCount: Int64(recordingsBytes), countStyle: .file)
    }

    package var formattedDatabase: String {
        ByteCountFormatter.string(fromByteCount: Int64(databaseBytes), countStyle: .file)
    }
}
