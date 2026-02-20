// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "OtherVoices",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "OtherVoices",
            path: "Sources",
            linkerSettings: [
                .linkedLibrary("sqlite3"),
                .linkedFramework("AVFoundation"),
            ]
        ),
    ]
)
