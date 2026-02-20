import Foundation
import OSLog
import SQLite3

private let logger = Logger(subsystem: "com.user.other-voices", category: "database")

/// All columns — used by getCall() for full detail loading
private let allColumns = """
    session_id, app_name, started_at, ended_at, duration_seconds,
    system_wav_path, mic_wav_path, transcript, summary_json,
    template_name, notes, transcript_segments
    """

/// Lightweight columns for list views — skips transcript and transcript_segments
private let listColumns = """
    session_id, app_name, started_at, ended_at, duration_seconds,
    system_wav_path, mic_wav_path, NULL, summary_json,
    template_name, notes, NULL
    """

final class SQLiteDatabase {
    private let path: String
    private var db: OpaquePointer?

    init(path: String) {
        self.path = path
        let exists = FileManager.default.fileExists(atPath: path)
        logger.warning("DB path: \(path), exists: \(exists)")
    }

    deinit {
        if let db {
            sqlite3_close(db)
        }
    }

    private func ensureOpen() -> OpaquePointer? {
        if let db { return db }

        var handle: OpaquePointer?
        let flags = SQLITE_OPEN_READWRITE
        let rc = sqlite3_open_v2(path, &handle, flags, nil)
        guard rc == SQLITE_OK else {
            let err = handle.flatMap { String(cString: sqlite3_errmsg($0)) } ?? "unknown"
            logger.error("open failed: \(err) (code \(rc))")
            if let handle { sqlite3_close(handle) }
            return nil
        }
        sqlite3_exec(handle, "PRAGMA journal_mode=WAL", nil, nil, nil)
        self.db = handle
        return handle
    }

    func listRecent(limit: Int = 100) -> [Call] {
        guard let db = ensureOpen() else { return [] }

        let sql = "SELECT \(listColumns) FROM calls ORDER BY started_at DESC LIMIT ?"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_int(stmt, 1, Int32(limit))
        return readCalls(stmt: stmt!)
    }

    func listByApp(_ appName: String, limit: Int = 100) -> [Call] {
        guard let db = ensureOpen() else { return [] }

        let sql = "SELECT \(listColumns) FROM calls WHERE app_name = ? ORDER BY started_at DESC LIMIT ?"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (appName as NSString).utf8String, -1, nil)
        sqlite3_bind_int(stmt, 2, Int32(limit))
        return readCalls(stmt: stmt!)
    }

    func getCall(_ sessionId: String) -> Call? {
        guard let db = ensureOpen() else { return nil }

        let sql = "SELECT \(allColumns) FROM calls WHERE session_id = ?"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (sessionId as NSString).utf8String, -1, nil)
        let calls = readCalls(stmt: stmt!)
        return calls.first
    }

    func search(query: String, limit: Int = 50) -> [Call] {
        guard let db = ensureOpen() else { return [] }

        let sql = """
            SELECT c.session_id, c.app_name, c.started_at, c.ended_at, c.duration_seconds,
                   c.system_wav_path, c.mic_wav_path, NULL, c.summary_json,
                   c.template_name, c.notes, NULL
            FROM calls_fts fts
            JOIN calls c ON c.rowid = fts.rowid
            WHERE calls_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (query as NSString).utf8String, -1, nil)
        sqlite3_bind_int(stmt, 2, Int32(limit))
        return readCalls(stmt: stmt!)
    }

    func searchByEntity(name: String) -> [Call] {
        guard let db = ensureOpen() else { return [] }

        let sql = """
            SELECT c.session_id, c.app_name, c.started_at, c.ended_at, c.duration_seconds,
                   c.system_wav_path, c.mic_wav_path, NULL, c.summary_json,
                   c.template_name, c.notes, NULL
            FROM calls c
            JOIN entities e ON e.session_id = c.session_id
            WHERE e.name = ?
            ORDER BY c.started_at DESC
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (name as NSString).utf8String, -1, nil)
        return readCalls(stmt: stmt!)
    }

    func allEntities() -> [Entity] {
        guard let db = ensureOpen() else { return [] }

        let sql = "SELECT DISTINCT name, type FROM entities ORDER BY type, name"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        var results: [Entity] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let name = String(cString: sqlite3_column_text(stmt, 0))
            let type = String(cString: sqlite3_column_text(stmt, 1))
            results.append(Entity(name: name, type: type))
        }
        return results
    }

    func entityCounts() -> [String: Int] {
        guard let db = ensureOpen() else { return [:] }

        let sql = "SELECT name, COUNT(DISTINCT session_id) as cnt FROM entities GROUP BY name"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [:] }
        defer { sqlite3_finalize(stmt) }

        var results: [String: Int] = [:]
        while sqlite3_step(stmt) == SQLITE_ROW {
            let name = String(cString: sqlite3_column_text(stmt, 0))
            let count = Int(sqlite3_column_int(stmt, 1))
            results[name] = count
        }
        return results
    }

    func updateNotes(sessionId: String, notes: String?) {
        guard let db = ensureOpen() else { return }

        let sql = "UPDATE calls SET notes = ? WHERE session_id = ?"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }

        if let notes = notes {
            sqlite3_bind_text(stmt, 1, (notes as NSString).utf8String, -1, nil)
        } else {
            sqlite3_bind_null(stmt, 1)
        }
        sqlite3_bind_text(stmt, 2, (sessionId as NSString).utf8String, -1, nil)
        sqlite3_step(stmt)
    }

    func appCounts() -> [(String, Int)] {
        guard let db = ensureOpen() else { return [] }

        let sql = "SELECT app_name, COUNT(*) as cnt FROM calls GROUP BY app_name ORDER BY cnt DESC"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        var results: [(String, Int)] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let name = String(cString: sqlite3_column_text(stmt, 0))
            let count = Int(sqlite3_column_int(stmt, 1))
            results.append((name, count))
        }
        return results
    }

    func totalCount() -> Int {
        guard let db = ensureOpen() else { return 0 }

        let sql = "SELECT COUNT(*) FROM calls"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return 0 }
        defer { sqlite3_finalize(stmt) }

        if sqlite3_step(stmt) == SQLITE_ROW {
            return Int(sqlite3_column_int(stmt, 0))
        }
        return 0
    }

    func actionItemCalls(days: Int = 7) -> [Call] {
        guard let db = ensureOpen() else { return [] }

        let sql = """
            SELECT \(listColumns)
            FROM calls
            WHERE summary_json IS NOT NULL
              AND started_at >= datetime('now', ?)
            ORDER BY started_at DESC
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        let param = "-\(days) days"
        sqlite3_bind_text(stmt, 1, (param as NSString).utf8String, -1, nil)

        return readCalls(stmt: stmt!).filter { call in
            guard let summary = call.summary else { return false }
            return summary.actionItems != nil && !(summary.actionItems!.isEmpty)
        }
    }

    // MARK: - Commitments

    func getCommitments(sessionId: String) -> [Commitment] {
        guard let db = ensureOpen() else { return [] }

        let sql = """
            SELECT id, session_id, direction, who_label, who_name, to_label, to_name,
                   text, verbatim_quote, timestamp, deadline_raw, deadline_type,
                   significance, uncertain, status, created_at, resolved_at
            FROM commitments WHERE session_id = ? ORDER BY id
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (sessionId as NSString).utf8String, -1, nil)
        return readCommitments(stmt: stmt!)
    }

    func getOpenCommitments(direction: String? = nil) -> [Commitment] {
        guard let db = ensureOpen() else { return [] }

        let sql: String
        if direction != nil {
            sql = """
                SELECT cm.id, cm.session_id, cm.direction, cm.who_label, cm.who_name,
                       cm.to_label, cm.to_name, cm.text, cm.verbatim_quote, cm.timestamp,
                       cm.deadline_raw, cm.deadline_type, cm.significance, cm.uncertain,
                       cm.status, cm.created_at, cm.resolved_at,
                       c.app_name, c.started_at
                FROM commitments cm
                JOIN calls c ON c.session_id = cm.session_id
                WHERE cm.status = 'open' AND cm.direction = ?
                ORDER BY cm.created_at DESC
                """
        } else {
            sql = """
                SELECT cm.id, cm.session_id, cm.direction, cm.who_label, cm.who_name,
                       cm.to_label, cm.to_name, cm.text, cm.verbatim_quote, cm.timestamp,
                       cm.deadline_raw, cm.deadline_type, cm.significance, cm.uncertain,
                       cm.status, cm.created_at, cm.resolved_at,
                       c.app_name, c.started_at
                FROM commitments cm
                JOIN calls c ON c.session_id = cm.session_id
                WHERE cm.status = 'open'
                ORDER BY cm.created_at DESC
                """
        }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        if direction != nil {
            sqlite3_bind_text(stmt, 1, (direction! as NSString).utf8String, -1, nil)
        }
        return readCommitments(stmt: stmt!, includeCallInfo: true)
    }

    func commitmentCounts() -> (outgoing: Int, incoming: Int) {
        guard let db = ensureOpen() else { return (0, 0) }

        let sql = """
            SELECT direction, COUNT(*) as cnt
            FROM commitments WHERE status = 'open'
            GROUP BY direction
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return (0, 0) }
        defer { sqlite3_finalize(stmt) }

        var outgoing = 0
        var incoming = 0
        while sqlite3_step(stmt) == SQLITE_ROW {
            let dir = String(cString: sqlite3_column_text(stmt, 0))
            let cnt = Int(sqlite3_column_int(stmt, 1))
            if dir == "outgoing" { outgoing = cnt }
            else if dir == "incoming" { incoming = cnt }
        }
        return (outgoing, incoming)
    }

    func updateCommitmentStatus(commitmentId: Int, status: String) {
        guard let db = ensureOpen() else { return }

        let sql: String
        if status == "done" || status == "dismissed" {
            sql = "UPDATE commitments SET status = ?, resolved_at = datetime('now') WHERE id = ?"
        } else {
            sql = "UPDATE commitments SET status = ?, resolved_at = NULL WHERE id = ?"
        }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (status as NSString).utf8String, -1, nil)
        sqlite3_bind_int(stmt, 2, Int32(commitmentId))
        sqlite3_step(stmt)
    }

    // MARK: - Person Detail (cross-call temporal connections)

    /// All commitments where who_name or to_name matches person name, with call info
    func commitmentsByPerson(name: String) -> [Commitment] {
        guard let db = ensureOpen() else { return [] }

        let sql = """
            SELECT cm.id, cm.session_id, cm.direction, cm.who_label, cm.who_name,
                   cm.to_label, cm.to_name, cm.text, cm.verbatim_quote, cm.timestamp,
                   cm.deadline_raw, cm.deadline_type, cm.significance, cm.uncertain,
                   cm.status, cm.created_at, cm.resolved_at,
                   c.app_name, c.started_at
            FROM commitments cm
            JOIN calls c ON c.session_id = cm.session_id
            WHERE cm.who_name = ? OR cm.to_name = ?
            ORDER BY cm.created_at DESC
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (name as NSString).utf8String, -1, nil)
        sqlite3_bind_text(stmt, 2, (name as NSString).utf8String, -1, nil)
        return readCommitments(stmt: stmt!, includeCallInfo: true)
    }

    /// Person stats: first/last call date, total duration, app breakdown
    struct PersonStats {
        let totalCalls: Int
        let firstCallDate: Date?
        let lastCallDate: Date?
        let totalDuration: Double
        let appBreakdown: [(String, Int)]  // (appName, count)
    }

    func personStats(name: String) -> PersonStats {
        guard let db = ensureOpen() else {
            return PersonStats(totalCalls: 0, firstCallDate: nil, lastCallDate: nil,
                             totalDuration: 0, appBreakdown: [])
        }

        // Aggregate stats
        let sql = """
            SELECT COUNT(*), MIN(c.started_at), MAX(c.started_at), SUM(c.duration_seconds)
            FROM calls c
            JOIN entities e ON e.session_id = c.session_id
            WHERE e.name = ?
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            return PersonStats(totalCalls: 0, firstCallDate: nil, lastCallDate: nil,
                             totalDuration: 0, appBreakdown: [])
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (name as NSString).utf8String, -1, nil)

        var totalCalls = 0
        var firstDate: Date?
        var lastDate: Date?
        var totalDuration: Double = 0

        if sqlite3_step(stmt) == SQLITE_ROW {
            totalCalls = Int(sqlite3_column_int(stmt, 0))
            firstDate = columnText(stmt!, 1).map { Call.parseDate($0) }
            lastDate = columnText(stmt!, 2).map { Call.parseDate($0) }
            totalDuration = sqlite3_column_double(stmt, 3)
        }

        // App breakdown
        let appSql = """
            SELECT c.app_name, COUNT(*) as cnt
            FROM calls c
            JOIN entities e ON e.session_id = c.session_id
            WHERE e.name = ?
            GROUP BY c.app_name
            ORDER BY cnt DESC
            """
        var appStmt: OpaquePointer?
        var apps: [(String, Int)] = []
        if sqlite3_prepare_v2(db, appSql, -1, &appStmt, nil) == SQLITE_OK {
            defer { sqlite3_finalize(appStmt) }
            sqlite3_bind_text(appStmt, 1, (name as NSString).utf8String, -1, nil)
            while sqlite3_step(appStmt) == SQLITE_ROW {
                let appName = String(cString: sqlite3_column_text(appStmt, 0))
                let count = Int(sqlite3_column_int(appStmt, 1))
                apps.append((appName, count))
            }
        }

        return PersonStats(totalCalls: totalCalls, firstCallDate: firstDate,
                          lastCallDate: lastDate, totalDuration: totalDuration,
                          appBreakdown: apps)
    }

    // MARK: - Private

    private func readCommitments(stmt: OpaquePointer, includeCallInfo: Bool = false) -> [Commitment] {
        var results: [Commitment] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let appName: String?
            let callStartedAt: Date?
            if includeCallInfo {
                appName = columnText(stmt, 17)
                callStartedAt = columnText(stmt, 18).flatMap { Call.parseDate($0) }
            } else {
                appName = nil
                callStartedAt = nil
            }
            results.append(Commitment(
                id: Int(sqlite3_column_int(stmt, 0)),
                sessionId: columnText(stmt, 1) ?? "",
                direction: columnText(stmt, 2) ?? "outgoing",
                whoLabel: columnText(stmt, 3) ?? "",
                whoName: columnText(stmt, 4),
                toLabel: columnText(stmt, 5),
                toName: columnText(stmt, 6),
                text: columnText(stmt, 7) ?? "",
                verbatimQuote: columnText(stmt, 8),
                timestamp: columnText(stmt, 9),
                deadlineRaw: columnText(stmt, 10),
                deadlineType: columnText(stmt, 11),
                significance: columnText(stmt, 12),
                uncertain: sqlite3_column_int(stmt, 13) != 0,
                status: columnText(stmt, 14) ?? "open",
                createdAt: columnText(stmt, 15),
                resolvedAt: columnText(stmt, 16),
                appName: appName,
                callStartedAt: callStartedAt
            ))
        }
        return results
    }

    private func readCalls(stmt: OpaquePointer) -> [Call] {
        var calls: [Call] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let call = Call(
                sessionId: columnText(stmt, 0) ?? "",
                appName: columnText(stmt, 1) ?? "",
                startedAt: Call.parseDate(columnText(stmt, 2) ?? ""),
                endedAt: Call.parseDate(columnText(stmt, 3) ?? ""),
                durationSeconds: sqlite3_column_double(stmt, 4),
                systemWavPath: columnText(stmt, 5),
                micWavPath: columnText(stmt, 6),
                transcript: columnText(stmt, 7),
                summaryJson: columnText(stmt, 8),
                templateName: columnText(stmt, 9),
                notes: columnText(stmt, 10),
                transcriptSegmentsJson: columnText(stmt, 11)
            )
            calls.append(call)
        }
        return calls
    }

    private func columnText(_ stmt: OpaquePointer, _ index: Int32) -> String? {
        guard let cStr = sqlite3_column_text(stmt, index) else { return nil }
        return String(cString: cStr)
    }
}
