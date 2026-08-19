// call-signal — one-shot physical call-signal probe.
//
// Prints JSON to stdout and exits:
//   {"mic_processes": [{"pid": 123, "name": "zoom.us"}], "camera_on": true}
//
// mic_processes — processes currently running audio INPUT (the OS-level truth
// behind the orange mic indicator), via the CoreAudio per-process API
// (macOS 14.4+). camera_on — any camera device running somewhere (CMIO).
// Both are status reads; no TCC permission is required.
//
// One-shot reads on purpose: on macOS 26 (Tahoe) the IsRunningInput listener
// callbacks are unreliable, but property reads are correct. The Python daemon
// polls this binary every few seconds.

import AppKit
import CoreAudio
import CoreMediaIO
import Foundation

// MARK: - CoreAudio: processes running audio input

func micProcesses() -> [[String: Any]] {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyProcessObjectList,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain
    )

    var dataSize: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(
        AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize
    ) == noErr, dataSize > 0 else { return [] }

    let count = Int(dataSize) / MemoryLayout<AudioObjectID>.size
    var processObjects = [AudioObjectID](repeating: 0, count: count)
    guard AudioObjectGetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &dataSize,
        &processObjects
    ) == noErr else { return [] }

    var result: [[String: Any]] = []
    for obj in processObjects {
        var runningInput: UInt32 = 0
        var size = UInt32(MemoryLayout<UInt32>.size)
        var runningAddress = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyIsRunningInput,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        guard AudioObjectGetPropertyData(
            obj, &runningAddress, 0, nil, &size, &runningInput
        ) == noErr, runningInput != 0 else { continue }

        var pid: pid_t = 0
        var pidSize = UInt32(MemoryLayout<pid_t>.size)
        var pidAddress = AudioObjectPropertyAddress(
            mSelector: kAudioProcessPropertyPID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        guard AudioObjectGetPropertyData(
            obj, &pidAddress, 0, nil, &pidSize, &pid
        ) == noErr else { continue }

        var name = "unknown"
        if let app = NSRunningApplication(processIdentifier: pid),
           let localized = app.localizedName {
            name = localized
        } else {
            // Fall back to the BSD process name for non-app processes
            var buffer = [CChar](repeating: 0, count: 1024)
            if proc_name(pid, &buffer, UInt32(buffer.count)) > 0 {
                name = String(cString: buffer)
            }
        }
        result.append(["pid": Int(pid), "name": name])
    }
    return result
}

// MARK: - CMIO: any camera running

func cameraOn() -> Bool {
    var address = CMIOObjectPropertyAddress(
        mSelector: CMIOObjectPropertySelector(kCMIOHardwarePropertyDevices),
        mScope: CMIOObjectPropertyScope(kCMIOObjectPropertyScopeGlobal),
        mElement: CMIOObjectPropertyElement(kCMIOObjectPropertyElementMain)
    )

    var dataSize: UInt32 = 0
    guard CMIOObjectGetPropertyDataSize(
        CMIOObjectID(kCMIOObjectSystemObject), &address, 0, nil, &dataSize
    ) == noErr, dataSize > 0 else { return false }

    let count = Int(dataSize) / MemoryLayout<CMIOObjectID>.size
    var devices = [CMIOObjectID](repeating: 0, count: count)
    var dataUsed: UInt32 = 0
    guard CMIOObjectGetPropertyData(
        CMIOObjectID(kCMIOObjectSystemObject), &address, 0, nil, dataSize,
        &dataUsed, &devices
    ) == noErr else { return false }

    for device in devices {
        var running: UInt32 = 0
        var size: UInt32 = 0
        var runningAddress = CMIOObjectPropertyAddress(
            mSelector: CMIOObjectPropertySelector(
                kCMIODevicePropertyDeviceIsRunningSomewhere
            ),
            mScope: CMIOObjectPropertyScope(kCMIOObjectPropertyScopeGlobal),
            mElement: CMIOObjectPropertyElement(kCMIOObjectPropertyElementMain)
        )
        guard CMIOObjectGetPropertyDataSize(
            device, &runningAddress, 0, nil, &size
        ) == noErr, size > 0 else { continue }
        guard CMIOObjectGetPropertyData(
            device, &runningAddress, 0, nil, size, &dataUsed, &running
        ) == noErr else { continue }
        if running != 0 { return true }
    }
    return false
}

// MARK: - Main

let payload: [String: Any] = [
    "mic_processes": micProcesses(),
    "camera_on": cameraOn(),
]

if let data = try? JSONSerialization.data(withJSONObject: payload),
   let json = String(data: data, encoding: .utf8) {
    print(json)
} else {
    print("{\"mic_processes\": [], \"camera_on\": false}")
}
