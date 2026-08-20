// calendar-peek — one-shot EventKit probe for upcoming events.
//
// Usage: calendar-peek [horizon-hours]   (default 2)
//
// Prints a JSON array to stdout and exits:
//   [{"id": "...", "title": "...", "start": "2026-08-20T14:05:00Z",
//     "attendees": ["Имя или email", ...]}, ...]
//
// All events in the horizon are printed (with or without attendees) — the
// Python daemon filters. When Calendar access is not granted (or the request
// fails) it prints {"error": "no-access"} and exits 0: the daemon treats the
// helper as optional equipment and must never crash because of it.
//
// requestFullAccessToEvents is the macOS 14+ API; the TCC prompt attributes
// to the responsible process (the terminal / launchd job). The usage string
// lives in an __info_plist section embedded at link time (see setup.sh) so
// the bare binary can be prompted at all.
//
// One-shot on purpose, same as call-signal: the Python daemon polls this
// binary every couple of minutes; no listeners, no runloop.

import EventKit
import Foundation

func printJSON(_ obj: Any) {
    if let data = try? JSONSerialization.data(withJSONObject: obj),
       let json = String(data: data, encoding: .utf8) {
        print(json)
    } else {
        print("{\"error\": \"no-access\"}")
    }
}

// MARK: - Horizon argument (hours, default 2)

var horizonHours = 2.0
if CommandLine.arguments.count > 1,
   let parsed = Double(CommandLine.arguments[1]), parsed > 0 {
    horizonHours = parsed
}

// MARK: - Calendar access

let store = EKEventStore()
let semaphore = DispatchSemaphore(value: 0)
var granted = false

store.requestFullAccessToEvents { ok, _ in
    granted = ok
    semaphore.signal()
}
// The TCC prompt can sit unanswered; don't hang the daemon's subprocess
// timeout budget forever.
_ = semaphore.wait(timeout: .now() + 25)

guard granted else {
    printJSON(["error": "no-access"])
    exit(0)
}

// MARK: - Events in the horizon

let now = Date()
let end = now.addingTimeInterval(horizonHours * 3600)
let predicate = store.predicateForEvents(withStart: now, end: end, calendars: nil)
let events = store.events(matching: predicate)

let iso = ISO8601DateFormatter()
var payload: [[String: Any]] = []
for event in events {
    let attendees: [String] = (event.attendees ?? []).compactMap { participant in
        if let name = participant.name, !name.isEmpty {
            return name
        }
        let url = participant.url.absoluteString
        if url.lowercased().hasPrefix("mailto:") {
            return String(url.dropFirst("mailto:".count))
        }
        return url.isEmpty ? nil : url
    }
    payload.append([
        "id": event.eventIdentifier ?? "\(event.title ?? "")@\(iso.string(from: event.startDate))",
        "title": event.title ?? "",
        "start": iso.string(from: event.startDate),
        "attendees": attendees,
    ])
}
printJSON(payload)
