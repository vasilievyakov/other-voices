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

package final class SQLiteDatabase {
    private let path: String
    private var db: OpaquePointer?

    /// Cutoff string comparable to stored started_at values, which are naive
    /// local isoformat — SQLite's datetime('now') is UTC with a space
    /// separator and never compares correctly against them.
    package static func actionItemCutoff(days: Int, from reference: Date = Date()) -> String {
        Call.naiveLocalBasic.string(
            from: reference.addingTimeInterval(-Double(days) * 86400))
    }

    package init(path: String) {
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

    package func openCommitments() -> [Commitment] {
        guard let db = ensureOpen() else { return [] }

        let sql = """
        SELECT c.id, c.session_id, c.direction,
               COALESCE(NULLIF(c.who_name, ''), c.who_label) AS who,
               c.text, c.verbatim_quote, c.deadline_raw, c.uncertain,
               ca.app_name, COALESCE(ca.started_at, ''),
               c.title, c.deadline_date
        FROM commitments c
        JOIN calls ca ON ca.session_id = c.session_id
        WHERE c.status = 'open'
        ORDER BY ca.started_at DESC, c.id
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        func text(_ idx: Int32) -> String? {
            guard let c = sqlite3_column_text(stmt, idx) else { return nil }
            return String(cString: c)
        }

        var results: [Commitment] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            results.append(
                Commitment(
                    id: Int(sqlite3_column_int64(stmt, 0)),
                    sessionId: text(1) ?? "",
                    direction: text(2) ?? "",
                    who: text(3) ?? "",
                    text: text(4) ?? "",
                    quote: text(5),
                    deadline: text(6),
                    uncertain: sqlite3_column_int(stmt, 7) != 0,
                    appName: text(8) ?? "",
                    callDate: String((text(9) ?? "").prefix(10)),
                    title: text(10),
                    deadlineDate: text(11)
                )
            )
        }
        return results
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
              AND started_at >= ?
            ORDER BY started_at DESC
            """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        let param = Self.actionItemCutoff(days: days)
        sqlite3_bind_text(stmt, 1, (param as NSString).utf8String, -1, nil)

        return readCalls(stmt: stmt!).filter { call in
            guard let summary = call.summary else { return false }
            return summary.actionItems != nil && !(summary.actionItems!.isEmpty)
        }
    }

    // MARK: - Speaker Names

    /// The app can meet a database the Python migration hasn't touched yet —
    /// same definition as src/database.py so whoever runs first wins cleanly.
    private func ensureSpeakerNamesTable(_ db: OpaquePointer) {
        let sql = """
            CREATE TABLE IF NOT EXISTS speaker_names (
                session_id TEXT NOT NULL REFERENCES calls(session_id) ON DELETE CASCADE,
                label      TEXT NOT NULL,
                name       TEXT NOT NULL,
                PRIMARY KEY (session_id, label)
            )
            """
        sqlite3_exec(db, sql, nil, nil, nil)
    }

    /// Owner-set label -> name mapping for one session.
    package func speakerNames(sessionId: String) -> [String: String] {
        guard let db = ensureOpen() else { return [:] }

        let sql = "SELECT label, name FROM speaker_names WHERE session_id = ?"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [:] }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_text(stmt, 1, (sessionId as NSString).utf8String, -1, nil)
        var results: [String: String] = [:]
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let label = columnText(stmt!, 0), let name = columnText(stmt!, 1) {
                results[label] = name
            }
        }
        return results
    }

    /// Owner-set display name for a diarization label. Mirrors the Python
    /// side: writes the mapping and pushes the name into commitments.who_name
    /// (and to_name where to_label matches) for this session. An empty name
    /// removes the mapping and returns those columns to NULL.
    package func setSpeakerName(sessionId: String, label: String, name: String) {
        guard let db = ensureOpen() else { return }
        ensureSpeakerNamesTable(db)

        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let value: String? = trimmed.isEmpty ? nil : trimmed

        if let value {
            run(db,
                "INSERT OR REPLACE INTO speaker_names (session_id, label, name) VALUES (?, ?, ?)",
                [sessionId, label, value])
        } else {
            run(db,
                "DELETE FROM speaker_names WHERE session_id = ? AND label = ?",
                [sessionId, label])
        }
        run(db,
            "UPDATE commitments SET who_name = ? WHERE session_id = ? AND who_label = ?",
            [value, sessionId, label])
        run(db,
            "UPDATE commitments SET to_name = ? WHERE session_id = ? AND to_label = ?",
            [value, sessionId, label])
    }

    @discardableResult
    private func run(_ db: OpaquePointer, _ sql: String, _ params: [String?]) -> Bool {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return false }
        defer { sqlite3_finalize(stmt) }
        for (i, param) in params.enumerated() {
            if let param {
                sqlite3_bind_text(stmt, Int32(i + 1), (param as NSString).utf8String, -1, nil)
            } else {
                sqlite3_bind_null(stmt, Int32(i + 1))
            }
        }
        return sqlite3_step(stmt) == SQLITE_DONE
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
