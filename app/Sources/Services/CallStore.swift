import Foundation
import OSLog

private let logger = Logger(subsystem: "com.user.other-voices", category: "store")

@Observable
package final class CallStore {
    var calls: [Call] = []
    var appCounts: [(String, Int)] = []
    var totalCount: Int = 0
    var searchQuery: String = ""
    var selectedFilter: SidebarItem = .allCalls
    var entities: [Entity] = []
    private var entityCounts: [String: Int] = [:]
    var commitmentCounts: (outgoing: Int, incoming: Int) = (0, 0)

    private let db: SQLiteDatabase
    private var statusMonitor: StatusMonitor?
    private var refreshTask: Task<Void, Never>?

    package init() {
        let dbPath = NSHomeDirectory() + "/call-recorder/data/calls.db"
        self.db = SQLiteDatabase(path: dbPath)
        refresh()
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
                calls = db.search(query: searchQuery).filter { $0.appName == name }
            }
        case .entity(let name):
            calls = db.searchByEntity(name: name)
        case .commitments:
            calls = []
        }

        appCounts = db.appCounts()
        totalCount = db.totalCount()
        entities = db.allEntities()
        entityCounts = db.entityCounts()
        commitmentCounts = db.commitmentCounts()
    }

    func entityCallCount(_ name: String) -> Int? {
        entityCounts[name]
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

    func getCommitments(sessionId: String) -> [Commitment] {
        db.getCommitments(sessionId: sessionId)
    }

    func getOpenCommitments(direction: String? = nil) -> [Commitment] {
        db.getOpenCommitments(direction: direction)
    }

    func updateCommitmentStatus(id: Int, status: String) {
        db.updateCommitmentStatus(commitmentId: id, status: status)
        commitmentCounts = db.commitmentCounts()
    }

    private func startWatching() {
        let dataDir = NSHomeDirectory() + "/call-recorder/data"
        statusMonitor = StatusMonitor(directoryPath: dataDir) { [weak self] in
            self?.debouncedRefresh()
        }
        statusMonitor?.start()
    }

    private func debouncedRefresh() {
        refreshTask?.cancel()
        refreshTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            self?.refresh()
        }
    }
}
