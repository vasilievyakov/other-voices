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

// MARK: - Call Tests

func runCallTests() {
    print("\n--- CallTests ---")

    test("durationFormatted_minutes") {
        let call = makeCall(durationSeconds: 125)
        expect(call.durationFormatted == "2m05s", "got \(call.durationFormatted)")
    }

    test("durationFormatted_hours") {
        let call = makeCall(durationSeconds: 3661)
        expect(call.durationFormatted == "1h01m01s", "got \(call.durationFormatted)")
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
}

// MARK: - CallSummary Tests

func runCallSummaryTests() {
    print("\n--- CallSummaryTests ---")

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
}

// MARK: - ActionItem Tests

func runActionItemTests() {
    print("\n--- ActionItemTests ---")

    test("personExtraction") {
        let item = makeItem(text: "Подготовить RFC (@Вася, пятница)")
        expect(item.person == "Вася", "got \(item.person ?? "nil")")
    }

    test("noAtSign") {
        let item = makeItem(text: "Просто задача без упоминания")
        expect(item.person == nil)
    }

    test("edgeCases") {
        let item1 = makeItem(text: "Задача @Вася и @Петя")
        expect(item1.person == "Вася", "multiple @: got \(item1.person ?? "nil")")

        let item2 = makeItem(text: "Задача @")
        expect(item2.person == nil, "@ at end should be nil")

        let item3 = makeItem(text: "Задача @,nothing")
        expect(item3.person == nil, "@ with comma should be nil")
    }
}

// MARK: - Helpers

func makeCall(
    durationSeconds: Double = 600,
    appName: String = "Zoom",
    summaryJson: String? = nil
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
        summaryJson: summaryJson
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

// MARK: - Main

@main
struct TestRunner {
    static func main() {
        print("Other Voices — Swift Tests")
        runCallTests()
        runCallSummaryTests()
        runActionItemTests()

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
