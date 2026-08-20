import Foundation
import OtherVoicesLib
import SQLite3

// MARK: - Test DB helper

/// Creates a real SQLite file mimicking the daemon's schema BEFORE the Python
/// speaker_names migration ran — the app must cope with such a database.
private func makeTestDb() -> String {
    let dir = FileManager.default.temporaryDirectory
        .appendingPathComponent("ov-tests-\(UUID().uuidString)")
    try! FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let path = dir.appendingPathComponent("calls.db").path

    var db: OpaquePointer?
    guard sqlite3_open(path, &db) == SQLITE_OK else {
        fatalError("cannot create test db")
    }
    let schema = """
        CREATE TABLE calls (
            session_id TEXT PRIMARY KEY, app_name TEXT, started_at TEXT,
            ended_at TEXT, duration_seconds REAL, system_wav_path TEXT,
            mic_wav_path TEXT, transcript TEXT, summary_json TEXT,
            template_name TEXT, notes TEXT, transcript_segments TEXT
        );
        CREATE TABLE commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
            direction TEXT, who_label TEXT, who_name TEXT,
            to_label TEXT, to_name TEXT, text TEXT, verbatim_quote TEXT,
            timestamp TEXT, deadline_raw TEXT, deadline_type TEXT,
            significance TEXT, uncertain INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open', created_at TEXT, resolved_at TEXT,
            title TEXT, deadline_date TEXT
        );
        INSERT INTO calls (session_id, app_name, started_at, ended_at, duration_seconds)
        VALUES ('s1', 'Zoom', '2026-08-19T10:00:00', '2026-08-19T10:30:00', 1800.0),
               ('s2', 'Zoom', '2026-08-18T10:00:00', '2026-08-18T10:30:00', 1800.0);
        INSERT INTO commitments (session_id, direction, who_label, to_label, text, uncertain)
        VALUES ('s1', 'incoming', 'SPEAKER_1', 'SPEAKER_ME', 'прислать бриф', 0),
               ('s1', 'outgoing', 'SPEAKER_ME', 'SPEAKER_1', 'прислать смету', 0),
               ('s2', 'incoming', 'SPEAKER_1', 'SPEAKER_ME', 'чужая сессия', 0);
        """
    guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
        fatalError("cannot seed test db: \(String(cString: sqlite3_errmsg(db)))")
    }
    sqlite3_close(db)
    return path
}

/// Raw single-column text query against the test db for verification.
private func rawQuery(_ path: String, _ sql: String) -> [String?] {
    var db: OpaquePointer?
    guard sqlite3_open(path, &db) == SQLITE_OK else { return [] }
    defer { sqlite3_close(db) }
    var stmt: OpaquePointer?
    guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
    defer { sqlite3_finalize(stmt) }
    var out: [String?] = []
    while sqlite3_step(stmt) == SQLITE_ROW {
        if let c = sqlite3_column_text(stmt, 0) {
            out.append(String(cString: c))
        } else {
            out.append(nil)
        }
    }
    return out
}

// MARK: - TranscriptSegment speaker decoding

func runSegmentSpeakerTests() {
    print("\n--- TranscriptSegment Speaker Tests ---")

    test("segment_decodes_speaker") {
        let json = """
        {"start": 1.0, "end": 3.0, "text": "привет", "speaker": "SPEAKER_1"}
        """.data(using: .utf8)!
        let seg = try JSONDecoder().decode(TranscriptSegment.self, from: json)
        expect(seg.speaker == "SPEAKER_1", "got \(seg.speaker ?? "nil")")
    }

    test("segment_speaker_absent_is_nil") {
        let json = """
        {"start": 1.0, "end": 3.0, "text": "привет"}
        """.data(using: .utf8)!
        let seg = try JSONDecoder().decode(TranscriptSegment.self, from: json)
        expect(seg.speaker == nil, "got \(seg.speaker ?? "nil")")
    }

    test("segment_array_with_speakers") {
        let json = """
        [{"start":0.0,"end":2.0,"text":"привет","speaker":"SPEAKER_ME"},
         {"start":2.0,"end":4.0,"text":"здравствуйте","speaker":"SPEAKER_1"}]
        """.data(using: .utf8)!
        let segs = try JSONDecoder().decode([TranscriptSegment].self, from: json)
        expect(segs[0].speaker == "SPEAKER_ME")
        expect(segs[1].speaker == "SPEAKER_1")
    }
}

// MARK: - SpeakerDisplay substitution (display-time only, DB text untouched)

func runSpeakerDisplayTests() {
    print("\n--- SpeakerDisplay Tests ---")

    test("displayName_uses_mapping") {
        let names = ["SPEAKER_1": "Игорь"]
        expect(SpeakerDisplay.displayName(for: "SPEAKER_1", names: names) == "Игорь")
    }

    test("displayName_falls_back_to_label") {
        expect(SpeakerDisplay.displayName(for: "SPEAKER_2", names: ["SPEAKER_1": "Игорь"]) == "SPEAKER_2")
    }

    test("displayName_empty_name_falls_back") {
        expect(SpeakerDisplay.displayName(for: "SPEAKER_1", names: ["SPEAKER_1": ""]) == "SPEAKER_1")
    }

    test("substitute_replaces_labels_in_transcript") {
        let text = "[0:05] SPEAKER_ME: привет\n[0:10] SPEAKER_1: здравствуйте"
        let out = SpeakerDisplay.substitute(text, names: ["SPEAKER_1": "Игорь"])
        expect(out == "[0:05] SPEAKER_ME: привет\n[0:10] Игорь: здравствуйте", "got \(out)")
    }

    test("substitute_multiple_labels") {
        let text = "SPEAKER_1: a\nSPEAKER_2: b"
        let out = SpeakerDisplay.substitute(text, names: ["SPEAKER_1": "Игорь", "SPEAKER_2": "Маша"])
        expect(out == "Игорь: a\nМаша: b", "got \(out)")
    }

    test("substitute_does_not_eat_longer_label") {
        // SPEAKER_1 mapped, SPEAKER_10 must stay intact
        let text = "SPEAKER_1: a\nSPEAKER_10: b"
        let out = SpeakerDisplay.substitute(text, names: ["SPEAKER_1": "Игорь"])
        expect(out == "Игорь: a\nSPEAKER_10: b", "got \(out)")
    }

    test("substitute_empty_mapping_is_identity") {
        let text = "[0:05] SPEAKER_1: привет"
        expect(SpeakerDisplay.substitute(text, names: [:]) == text)
    }

    test("substitute_ignores_empty_names") {
        let text = "SPEAKER_1: привет"
        expect(SpeakerDisplay.substitute(text, names: ["SPEAKER_1": ""]) == text)
    }
}

// MARK: - SQLiteDatabase speaker names

func runSpeakerDbTests() {
    print("\n--- SQLiteDatabase Speaker Names Tests ---")

    test("speakerNames_empty_when_table_missing") {
        let db = SQLiteDatabase(path: makeTestDb())
        expect(db.speakerNames(sessionId: "s1").isEmpty, "should be empty")
    }

    test("setSpeakerName_roundtrip_creates_table") {
        // The table doesn't exist yet — setSpeakerName must create it.
        let db = SQLiteDatabase(path: makeTestDb())
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "Игорь")
        expect(db.speakerNames(sessionId: "s1") == ["SPEAKER_1": "Игорь"])
    }

    test("setSpeakerName_updates_commitments_who") {
        let db = SQLiteDatabase(path: makeTestDb())
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "Игорь")
        let open = db.openCommitments()
        let incoming = open.first { $0.sessionId == "s1" && $0.direction == "incoming" }
        expect(incoming?.who == "Игорь", "got \(incoming?.who ?? "nil")")
    }

    test("setSpeakerName_updates_to_name") {
        let path = makeTestDb()
        let db = SQLiteDatabase(path: path)
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "Игорь")
        let toNames = rawQuery(
            path,
            "SELECT to_name FROM commitments WHERE session_id='s1' AND to_label='SPEAKER_1'")
        expect(toNames == ["Игорь"], "got \(toNames)")
    }

    test("setSpeakerName_overwrite") {
        let db = SQLiteDatabase(path: makeTestDb())
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "Игорь")
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "Иван")
        expect(db.speakerNames(sessionId: "s1") == ["SPEAKER_1": "Иван"])
        let incoming = db.openCommitments().first {
            $0.sessionId == "s1" && $0.direction == "incoming"
        }
        expect(incoming?.who == "Иван", "got \(incoming?.who ?? "nil")")
    }

    test("setSpeakerName_empty_clears_mapping_and_names") {
        let path = makeTestDb()
        let db = SQLiteDatabase(path: path)
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "Игорь")
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "")
        expect(db.speakerNames(sessionId: "s1").isEmpty, "mapping should be gone")
        let incoming = db.openCommitments().first {
            $0.sessionId == "s1" && $0.direction == "incoming"
        }
        expect(incoming?.who == "SPEAKER_1", "who should fall back to label, got \(incoming?.who ?? "nil")")
        let whoNames = rawQuery(
            path,
            "SELECT who_name FROM commitments WHERE session_id='s1' AND who_label='SPEAKER_1'")
        expect(whoNames == [nil], "who_name should be NULL, got \(whoNames)")
        let toNames = rawQuery(
            path,
            "SELECT to_name FROM commitments WHERE session_id='s1' AND to_label='SPEAKER_1'")
        expect(toNames == [nil], "to_name should be NULL, got \(toNames)")
    }

    test("setSpeakerName_whitespace_treated_as_empty") {
        let db = SQLiteDatabase(path: makeTestDb())
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "   ")
        expect(db.speakerNames(sessionId: "s1").isEmpty)
    }

    test("setSpeakerName_other_sessions_untouched") {
        let path = makeTestDb()
        let db = SQLiteDatabase(path: path)
        db.setSpeakerName(sessionId: "s1", label: "SPEAKER_1", name: "Игорь")
        expect(db.speakerNames(sessionId: "s2").isEmpty, "s2 mapping must stay empty")
        let s2who = rawQuery(
            path,
            "SELECT who_name FROM commitments WHERE session_id='s2' AND who_label='SPEAKER_1'")
        expect(s2who == [nil], "s2 who_name must stay NULL, got \(s2who)")
    }
}
