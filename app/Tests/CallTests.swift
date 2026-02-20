import Foundation
import OtherVoicesLib

// Minimal test harness
var passed = 0
var failed = 0

func expect(_ condition: Bool, _ message: String = "", file: String = #file, line: Int = #line) {
    if condition {
        passed += 1
    } else {
        print("  FAIL [\(file.split(separator: "/").last ?? ""):\(line)] \(message)")
        failed += 1
    }
}

func test(_ name: String, _ body: () throws -> Void) {
    do {
        try body()
        print("  OK: \(name)")
    } catch {
        print("  FAIL: \(name) — \(error)")
        failed += 1
    }
}

// MARK: - Call Tests (7)

func runCallTests() {
    print("\n--- Call Tests ---")

    test("durationFormatted_seconds") {
        let call = makeCall(durationSeconds: 45)
        expect(call.durationFormatted == "0m45s", "got \(call.durationFormatted)")
    }

    test("durationFormatted_minutes") {
        let call = makeCall(durationSeconds: 125)
        expect(call.durationFormatted == "2m05s", "got \(call.durationFormatted)")
    }

    test("durationFormatted_exactMinute") {
        let call = makeCall(durationSeconds: 60)
        expect(call.durationFormatted == "1m00s", "got \(call.durationFormatted)")
    }

    test("durationFormatted_hours") {
        let call = makeCall(durationSeconds: 3661)
        expect(call.durationFormatted == "1h01m01s", "got \(call.durationFormatted)")
    }

    test("durationFormatted_exactHour") {
        let call = makeCall(durationSeconds: 3600)
        expect(call.durationFormatted == "1h00m00s", "got \(call.durationFormatted)")
    }

    test("appIconMapping") {
        let cases: [(String, String)] = [
            ("Zoom", "video.fill"),
            ("Google Meet", "globe"),
            ("Telegram", "bubble.left.fill"),
            ("FaceTime", "phone.fill"),
            ("Discord", "headphones"),
            ("Microsoft Teams", "person.3.fill"),
            ("Unknown", "phone.fill"),
        ]
        for (app, expectedIcon) in cases {
            let call = makeCall(appName: app)
            expect(call.appIcon == expectedIcon, "Icon mismatch for \(app): got \(call.appIcon)")
        }
    }

    test("parseDate_fractionalSeconds") {
        let date = Call.parseDate("2025-02-20T12:00:00.000Z")
        let c = Calendar(identifier: .gregorian).dateComponents(in: TimeZone(identifier: "UTC")!, from: date)
        expect(c.year == 2025, "year")
        expect(c.month == 2, "month")
        expect(c.day == 20, "day")
        expect(c.hour == 12, "hour")
    }

    test("parseDate_basic") {
        let date = Call.parseDate("2025-02-20T12:00:00Z")
        let c = Calendar(identifier: .gregorian).dateComponents(in: TimeZone(identifier: "UTC")!, from: date)
        expect(c.year == 2025, "year")
        expect(c.month == 2, "month")
        expect(c.day == 20, "day")
    }

    test("id_equals_sessionId") {
        let call = makeCall()
        expect(call.id == call.sessionId, "id should equal sessionId")
    }

    test("summaryNil_whenNoJson") {
        let call = makeCall(summaryJson: nil)
        expect(call.summary == nil, "summary should be nil when no JSON")
    }

    test("summaryNil_whenInvalidJson") {
        let call = makeCall(summaryJson: "not json at all")
        expect(call.summary == nil, "summary should be nil for invalid JSON")
    }

    test("templateName_default") {
        let call = makeCall()
        expect(call.templateName == "default", "templateName should default to 'default'")
    }

    test("templateName_custom") {
        let call = makeCall(templateName: "sales_call")
        expect(call.templateName == "sales_call", "got \(call.templateName ?? "nil")")
    }

    test("notes_nil_by_default") {
        let call = makeCall()
        expect(call.notes == nil, "notes should be nil by default")
    }

    test("notes_stored") {
        let call = makeCall(notes: "Important notes here")
        expect(call.notes == "Important notes here", "got \(call.notes ?? "nil")")
    }
}

// MARK: - CallSummary Tests (5)

func runCallSummaryTests() {
    print("\n--- CallSummary Tests ---")

    test("decodeFullJSON") {
        let json = """
        {
            "summary": "Обсудили план",
            "key_points": ["Пункт 1", "Пункт 2"],
            "decisions": ["Решение 1"],
            "action_items": ["Задача (@Вася)"],
            "participants": ["Вася", "Петя"]
        }
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(CallSummary.self, from: json)
        expect(s.summary == "Обсудили план")
        expect(s.keyPoints?.count == 2)
        expect(s.decisions?.first == "Решение 1")
        expect(s.actionItems?.first == "Задача (@Вася)")
        expect(s.participants?.count == 2)
    }

    test("decodePartialJSON") {
        let json = """
        {"summary": "Краткий звонок"}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(CallSummary.self, from: json)
        expect(s.summary == "Краткий звонок")
        expect(s.keyPoints == nil)
        expect(s.decisions == nil)
        expect(s.actionItems == nil)
        expect(s.participants == nil)
    }

    test("decodeEmptyArrays") {
        let json = """
        {"summary":"X","key_points":[],"decisions":[],"action_items":[],"participants":[]}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(CallSummary.self, from: json)
        expect(s.keyPoints != nil, "keyPoints should not be nil")
        expect(s.keyPoints?.count == 0)
        expect(s.actionItems?.count == 0)
    }

    test("callSummaryProperty") {
        let json = """
        {"summary":"Test","key_points":["A"],"decisions":[],"action_items":["Do X"],"participants":[]}
        """
        let call = makeCall(summaryJson: json)
        let s = call.summary
        expect(s != nil)
        expect(s?.summary == "Test")
        expect(s?.keyPoints == ["A"])
        expect(s?.actionItems == ["Do X"])
    }

    test("decodeCyrillicContent") {
        let json = """
        {"summary":"Обсудили архитектуру","key_points":["Микросервисы"],"action_items":["Написать RFC (@Вася)"]}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(CallSummary.self, from: json)
        expect(s.summary == "Обсудили архитектуру")
        expect(s.actionItems?.first == "Написать RFC (@Вася)")
    }

    test("decodeWithEntities") {
        let json = """
        {
            "summary": "Met with team",
            "entities": [
                {"name": "Вася", "type": "person"},
                {"name": "Acme Corp", "type": "company"}
            ]
        }
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(CallSummary.self, from: json)
        expect(s.entities?.count == 2, "entities count")
        expect(s.entities?.first?.name == "Вася")
        expect(s.entities?.first?.isPerson == true)
        expect(s.entities?.last?.isCompany == true)
    }

    test("decodeWithoutEntities") {
        let json = """
        {"summary": "No entities here"}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(CallSummary.self, from: json)
        expect(s.entities == nil, "entities should be nil when not present")
    }
}

// MARK: - Entity Tests (4)

func runEntityTests() {
    print("\n--- Entity Tests ---")

    test("entity_person") {
        let e = Entity(name: "Вася", type: "person")
        expect(e.isPerson == true)
        expect(e.isCompany == false)
        expect(e.icon == "person.fill")
        expect(e.id == "person:Вася")
    }

    test("entity_company") {
        let e = Entity(name: "Acme Corp", type: "company")
        expect(e.isPerson == false)
        expect(e.isCompany == true)
        expect(e.icon == "building.2.fill")
        expect(e.id == "company:Acme Corp")
    }

    test("entity_hashable") {
        let a = Entity(name: "Вася", type: "person")
        let b = Entity(name: "Вася", type: "person")
        expect(a == b, "same entity should be equal")
    }

    test("entity_codable") {
        let json = """
        {"name": "Test Corp", "type": "company"}
        """.data(using: .utf8)!
        let e = try JSONDecoder().decode(Entity.self, from: json)
        expect(e.name == "Test Corp")
        expect(e.type == "company")
    }
}

// MARK: - ActionItem Tests (5)

func runActionItemTests() {
    print("\n--- ActionItem Tests ---")

    test("personExtraction_parentheses") {
        let item = makeItem(text: "Подготовить RFC (@Вася, пятница)")
        expect(item.person == "Вася", "got \(item.person ?? "nil")")
    }

    test("personExtraction_space") {
        let item = makeItem(text: "Задача @Петя до конца недели")
        expect(item.person == "Петя", "got \(item.person ?? "nil")")
    }

    test("noAtSign") {
        let item = makeItem(text: "Просто задача без упоминания")
        expect(item.person == nil)
    }

    test("atAtEnd") {
        let item = makeItem(text: "Задача @")
        expect(item.person == nil, "@ at end should be nil")
    }

    test("atWithComma") {
        let item = makeItem(text: "Задача @,nothing")
        expect(item.person == nil, "@ with comma should be nil")
    }

    test("multipleAt_firstExtracted") {
        let item = makeItem(text: "Задача @Вася и @Петя")
        expect(item.person == "Вася", "first @ should be extracted, got \(item.person ?? "nil")")
    }
}

// MARK: - DaemonStatus Tests (8)

func runDaemonStatusTests() {
    print("\n--- DaemonStatus Tests ---")

    test("decodeFromJSON") {
        let json = """
        {"daemon_pid":123,"timestamp":"2025-02-20T12:00:00Z","state":"idle","app_name":null,"session_id":null,"started_at":null,"pipeline":null}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(DaemonStatus.self, from: json)
        expect(s.daemonPid == 123)
        expect(s.state == "idle")
        expect(s.appName == nil)
    }

    test("isActive_idle") {
        let s = makeDaemonStatus(state: "idle")
        expect(s.isActive == true, "idle should be active")
    }

    test("isActive_stopped") {
        let s = makeDaemonStatus(state: "stopped")
        expect(s.isActive == false, "stopped should not be active")
    }

    test("isRecording") {
        let s = makeDaemonStatus(state: "recording")
        expect(s.isRecording == true)
        expect(s.isProcessing == false)
    }

    test("isProcessing") {
        let s = makeDaemonStatus(state: "processing")
        expect(s.isProcessing == true)
        expect(s.isRecording == false)
    }

    test("stateLabel_recording") {
        let s = makeDaemonStatus(state: "recording")
        expect(s.stateLabel == "Recording", "got \(s.stateLabel)")
    }

    test("stateLabel_processing_pipelines") {
        let cases: [(String?, String)] = [
            ("transcribing", "Transcribing"),
            ("summarizing", "Summarizing"),
            ("saving", "Saving"),
            (nil, "Processing"),
        ]
        for (pipeline, expected) in cases {
            let s = makeDaemonStatus(state: "processing", pipeline: pipeline)
            expect(s.stateLabel == expected, "pipeline \(pipeline ?? "nil") → \(s.stateLabel), expected \(expected)")
        }
    }

    test("stateLabel_idle_stopped") {
        expect(makeDaemonStatus(state: "idle").stateLabel == "Idle")
        expect(makeDaemonStatus(state: "stopped").stateLabel == "Stopped")
    }

    test("stateLabel_unknown_capitalized") {
        let s = makeDaemonStatus(state: "custom")
        expect(s.stateLabel == "Custom", "got \(s.stateLabel)")
    }

    test("recordingDuration_nilWhenNoStartedAt") {
        let s = makeDaemonStatus(state: "idle", startedAt: nil)
        expect(s.recordingDuration == nil, "should be nil when no startedAt")
    }
}

// MARK: - SidebarItem Tests (5)

func runSidebarItemTests() {
    print("\n--- SidebarItem Tests ---")

    test("allCalls_label_icon") {
        let item = SidebarItem.allCalls
        expect(item.label == "All Calls", "label: \(item.label)")
        expect(item.icon == "phone.fill", "icon: \(item.icon)")
    }

    test("actionItems_label_icon") {
        let item = SidebarItem.actionItems
        expect(item.label == "Action Items", "label: \(item.label)")
        expect(item.icon == "checklist", "icon: \(item.icon)")
    }

    test("app_label_matches_name") {
        let item = SidebarItem.app("Zoom")
        expect(item.label == "Zoom", "label: \(item.label)")
    }

    test("app_icons") {
        let cases: [(String, String)] = [
            ("Zoom", "video.fill"),
            ("Google Meet", "globe"),
            ("Telegram", "bubble.left.fill"),
            ("FaceTime", "phone.fill"),
            ("Discord", "headphones"),
            ("Microsoft Teams", "person.3.fill"),
            ("Unknown", "phone.fill"),
        ]
        for (app, expectedIcon) in cases {
            let item = SidebarItem.app(app)
            expect(item.icon == expectedIcon, "\(app): got \(item.icon)")
        }
    }

    test("entity_label_icon") {
        let item = SidebarItem.entity("Вася")
        expect(item.label == "Вася", "label: \(item.label)")
        expect(item.icon == "person.fill", "icon: \(item.icon)")
    }

    test("hashable_equality") {
        let a = SidebarItem.allCalls
        let b = SidebarItem.allCalls
        expect(a == b, "allCalls should equal allCalls")

        let c = SidebarItem.app("Zoom")
        let d = SidebarItem.app("Zoom")
        expect(c == d, "app(Zoom) should equal app(Zoom)")

        let e = SidebarItem.app("Zoom")
        let f = SidebarItem.app("Teams")
        expect(e != f, "different apps should not be equal")
    }
}

// MARK: - Helpers

func makeCall(
    durationSeconds: Double = 600,
    appName: String = "Zoom",
    summaryJson: String? = nil,
    templateName: String? = "default",
    notes: String? = nil,
    transcriptSegmentsJson: String? = nil
) -> Call {
    let now = Date()
    return Call(
        sessionId: "test_001",
        appName: appName,
        startedAt: now,
        endedAt: now.addingTimeInterval(durationSeconds),
        durationSeconds: durationSeconds,
        systemWavPath: nil,
        micWavPath: nil,
        transcript: nil,
        summaryJson: summaryJson,
        templateName: templateName,
        notes: notes,
        transcriptSegmentsJson: transcriptSegmentsJson
    )
}

func makeItem(text: String) -> ActionItem {
    ActionItem(
        id: "test_0",
        text: text,
        sessionId: "s1",
        appName: "Zoom",
        callDate: Date(),
        callDateFormatted: "Feb 20, 2025"
    )
}

func makeDaemonStatus(
    state: String,
    pipeline: String? = nil,
    startedAt: String? = nil
) -> DaemonStatus {
    let json = """
    {"daemon_pid":1,"timestamp":"2025-02-20T12:00:00Z","state":"\(state)","app_name":null,"session_id":null,"started_at":\(startedAt.map { "\"\($0)\"" } ?? "null"),"pipeline":\(pipeline.map { "\"\($0)\"" } ?? "null")}
    """.data(using: .utf8)!
    return try! JSONDecoder().decode(DaemonStatus.self, from: json)
}

// MARK: - TranscriptSegment Tests (5)

func runTranscriptSegmentTests() {
    print("\n--- TranscriptSegment Tests ---")

    test("segment_startFormatted") {
        let seg = TranscriptSegment(start: 0.0, end: 5.2, text: "Hello")
        expect(seg.startFormatted == "0:00", "got \(seg.startFormatted)")
    }

    test("segment_endFormatted") {
        let seg = TranscriptSegment(start: 0.0, end: 65.0, text: "Hello")
        expect(seg.endFormatted == "1:05", "got \(seg.endFormatted)")
    }

    test("segment_rangeFormatted") {
        let seg = TranscriptSegment(start: 5.0, end: 12.0, text: "Test")
        expect(seg.rangeFormatted == "0:05-0:12", "got \(seg.rangeFormatted)")
    }

    test("segment_codable") {
        let json = """
        {"start": 1.5, "end": 3.0, "text": "Привет"}
        """.data(using: .utf8)!
        let seg = try JSONDecoder().decode(TranscriptSegment.self, from: json)
        expect(seg.start == 1.5, "start")
        expect(seg.end == 3.0, "end")
        expect(seg.text == "Привет", "text")
    }

    test("segment_array_codable") {
        let json = """
        [
            {"start": 0.0, "end": 2.5, "text": "Hello"},
            {"start": 2.5, "end": 5.0, "text": "World"}
        ]
        """.data(using: .utf8)!
        let segs = try JSONDecoder().decode([TranscriptSegment].self, from: json)
        expect(segs.count == 2, "count")
        expect(segs[0].text == "Hello")
        expect(segs[1].start == 2.5)
    }
}

// MARK: - Call.transcriptSegments Tests (3)

func runCallSegmentTests() {
    print("\n--- Call Transcript Segments Tests ---")

    test("transcriptSegments_nil_when_no_json") {
        let call = makeCall()
        expect(call.transcriptSegments == nil, "should be nil when no json")
    }

    test("transcriptSegments_parsed") {
        let segJson = """
        [{"start":0.0,"end":2.5,"text":"Hello"},{"start":2.5,"end":5.0,"text":"World"}]
        """
        let call = makeCall(transcriptSegmentsJson: segJson)
        let segs = call.transcriptSegments
        expect(segs != nil, "should not be nil")
        expect(segs?.count == 2, "count \(segs?.count ?? -1)")
        expect(segs?.first?.text == "Hello")
    }

    test("transcriptSegments_nil_on_invalid_json") {
        let call = makeCall(transcriptSegmentsJson: "not json")
        expect(call.transcriptSegments == nil, "invalid json should return nil")
    }
}

// MARK: - ChatMessage Tests (4)

func runChatMessageTests() {
    print("\n--- ChatMessage Tests ---")

    test("chatMessage_user") {
        let msg = ChatMessage(role: "user", content: "What happened?")
        expect(msg.isUser == true)
        expect(msg.isAssistant == false)
        expect(msg.content == "What happened?")
    }

    test("chatMessage_assistant") {
        let msg = ChatMessage(role: "assistant", content: "Meeting summary.")
        expect(msg.isUser == false)
        expect(msg.isAssistant == true)
    }

    test("chatMessage_identifiable") {
        let a = ChatMessage(role: "user", content: "Q")
        let b = ChatMessage(role: "user", content: "Q")
        // Different UUIDs
        expect(a.id != b.id, "different messages should have different IDs")
    }

    test("chatMessage_hashable") {
        let msg = ChatMessage(id: "test-id", role: "user", content: "Q")
        let copy = ChatMessage(id: "test-id", role: "user", content: "Q")
        expect(msg == copy, "same id should be equal")
    }
}

// MARK: - Template Tests (3)

func runTemplateTests() {
    print("\n--- Template Tests ---")

    test("defaultTemplates_notEmpty") {
        let templates = Template.defaultTemplates
        expect(templates.count >= 6, "at least 6 built-in templates, got \(templates.count)")
    }

    test("template_codable") {
        let json = """
        {"name": "sales_call", "display_name": "Sales Call", "description": "Sales"}
        """.data(using: .utf8)!
        let t = try JSONDecoder().decode(Template.self, from: json)
        expect(t.name == "sales_call")
        expect(t.displayName == "Sales Call")
        expect(t.id == "sales_call")
    }

    test("template_hashable") {
        let a = Template(name: "default", displayName: "Default", description: "Std")
        let b = Template(name: "default", displayName: "Default", description: "Std")
        expect(a == b, "same template should be equal")
    }
}

// MARK: - Main

@main
struct TestRunner {
    static func main() {
        print("Other Voices — Enterprise Swift Tests")
        runCallTests()
        runCallSummaryTests()
        runEntityTests()
        runActionItemTests()
        runDaemonStatusTests()
        runSidebarItemTests()
        runTranscriptSegmentTests()
        runCallSegmentTests()
        runChatMessageTests()
        runTemplateTests()

        print("\n=============================")
        print("\(passed) passed, \(failed) failed")
        if failed > 0 {
            print("TESTS FAILED")
            exit(1)
        } else {
            print("ALL TESTS PASSED")
        }
    }
}
