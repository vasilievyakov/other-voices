import Foundation
import OSLog

private let logger = Logger(subsystem: "com.user.other-voices", category: "store")

@Observable
final class CallStore {
    var calls: [Call] = []
    var appCounts: [(String, Int)] = []
    var totalCount: Int = 0
    var searchQuery: String = ""
    var selectedFilter: SidebarItem = .allCalls

    private let db: SQLiteDatabase
    private var statusMonitor: StatusMonitor?

    init() {
        let dbPath = NSHomeDirectory() + "/call-recorder/data/calls.db"
        let logMsg = "Home: \(NSHomeDirectory())\nDB: \(dbPath)\nExists: \(FileManager.default.fileExists(atPath: dbPath))"
        try? logMsg.write(toFile: "/tmp/ov-debug-init.txt", atomically: true, encoding: .utf8)
        self.db = SQLiteDatabase(path: dbPath)
        refresh()
        let logMsg2 = "Calls: \(calls.count), Total: \(totalCount), Apps: \(appCounts)"
        try? logMsg2.write(toFile: "/tmp/ov-debug-refresh.txt", atomically: true, encoding: .utf8)
        startWatching()
    }

    func refresh() {
        switch selectedFilter {
        case .allCalls:
            if searchQuery.isEmpty {
                calls = db.listRecent(limit: 200)
            } else {
                calls = db.search(query: searchQuery)
            }
        case .actionItems:
            calls = db.actionItemCalls(days: 30)
        case .app(let name):
            if searchQuery.isEmpty {
                calls = db.listByApp(name)
            } else {
                // Search within app: do full search then filter
                calls = db.search(query: searchQuery).filter { $0.appName == name }
            }
        }

        appCounts = db.appCounts()
        totalCount = db.totalCount()
    }

    func setFilter(_ filter: SidebarItem) {
        selectedFilter = filter
        refresh()
    }

    func setSearch(_ query: String) {
        searchQuery = query
        refresh()
    }

    func getCall(_ sessionId: String) -> Call? {
        db.getCall(sessionId)
    }

    func allActionItems(days: Int = 90) -> [ActionItem] {
        let calls = db.actionItemCalls(days: days)
        var items: [ActionItem] = []
        for call in calls {
            guard let summary = call.summary, let actions = summary.actionItems else { continue }
            for (idx, text) in actions.enumerated() {
                items.append(ActionItem(
                    id: "\(call.sessionId)_\(idx)",
                    text: text,
                    sessionId: call.sessionId,
                    appName: call.appName,
                    callDate: call.startedAt,
                    callDateFormatted: call.startedAtFormatted
                ))
            }
        }
        return items
    }

    private func startWatching() {
        let dataDir = NSHomeDirectory() + "/call-recorder/data"
        statusMonitor = StatusMonitor(directoryPath: dataDir) { [weak self] in
            // Debounce: only refresh if DB changed
            self?.refresh()
        }
        statusMonitor?.start()
    }
}
