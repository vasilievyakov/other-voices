import Foundation
import OSLog
import SQLite3

private let logger = Logger(subsystem: "com.user.other-voices", category: "database")

final class SQLiteDatabase {
    private let path: String

    init(path: String) {
        self.path = path
        let exists = FileManager.default.fileExists(atPath: path)
        logger.warning("DB path: \(path), exists: \(exists)")
    }

    private func open() -> OpaquePointer? {
        var db: OpaquePointer?
        let flags = SQLITE_OPEN_READWRITE
        let rc = sqlite3_open_v2(path, &db, flags, nil)
        guard rc == SQLITE_OK else {
            let err = db.flatMap { String(cString: sqlite3_errmsg($0)) } ?? "unknown"
            logger.error("open failed: \(err) (code \(rc))")
            if let db { sqlite3_close(db) }
            return nil
        }
        sqlite3_exec(db, "PRAGMA journal_mode=WAL", nil, nil, nil)
        return db
    }

    func listRecent(limit: Int = 100) -> [Call] {
        guard let db = open() else { return [] }
        defer { sqlite3_close(db) }

        let sql = """
            SELECT session_id, app_name, started_at, ended_at, duration_seconds,
                   system_wav_path, mic_wav_path, transcript, summary_json
            FROM calls ORDER BY started_at DESC LIMIT ?
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_int(stmt, 1, Int32(limit))
        return readCalls(stmt: stmt!)
    }

    func listByApp(_ appName: String, limit: Int = 100) -> [Call] {
        guard let db = open() else { return [] }
        defer { sqlite3_close(db) }

        let sql = """
            SELECT session_id, app_name, started_at, ended_at, duration_seconds,
                   system_wav_path, mic_wav_path, transcript, summary_json
            FROM calls WHERE app_name = ? ORDER BY started_at DESC LIMIT ?
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (appName as NSString).utf8String, -1, nil)
        sqlite3_bind_int(stmt, 2, Int32(limit))
        return readCalls(stmt: stmt!)
    }

    func getCall(_ sessionId: String) -> Call? {
        guard let db = open() else { return nil }
        defer { sqlite3_close(db) }

        let sql = """
            SELECT session_id, app_name, started_at, ended_at, duration_seconds,
                   system_wav_path, mic_wav_path, transcript, summary_json
            FROM calls WHERE session_id = ?
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return nil }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (sessionId as NSString).utf8String, -1, nil)
        let calls = readCalls(stmt: stmt!)
        return calls.first
    }

    func search(query: String, limit: Int = 50) -> [Call] {
        guard let db = open() else { return [] }
        defer { sqlite3_close(db) }

        let sql = """
            SELECT c.session_id, c.app_name, c.started_at, c.ended_at, c.duration_seconds,
                   c.system_wav_path, c.mic_wav_path, c.transcript, c.summary_json
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

    func appCounts() -> [(String, Int)] {
        guard let db = open() else { return [] }
        defer { sqlite3_close(db) }

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
        guard let db = open() else { return 0 }
        defer { sqlite3_close(db) }

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
        guard let db = open() else { return [] }
        defer { sqlite3_close(db) }

        let sql = """
            SELECT session_id, app_name, started_at, ended_at, duration_seconds,
                   system_wav_path, mic_wav_path, transcript, summary_json
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

    // MARK: - Private

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
                summaryJson: columnText(stmt, 8)
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
