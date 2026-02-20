// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "OtherVoices",
    platforms: [.macOS(.v14)],
    targets: [
        .target(
            name: "OtherVoicesLib",
            path: "Sources",
            exclude: ["App"],
            linkerSettings: [
                .linkedLibrary("sqlite3"),
                .linkedFramework("AVFoundation"),
            ]
        ),
        .executableTarget(
            name: "OtherVoices",
            dependencies: ["OtherVoicesLib"],
            path: "Sources/App"
        ),
        .executableTarget(
            name: "OtherVoicesTests",
            dependencies: ["OtherVoicesLib"],
            path: "Tests"
        ),
    ]
)
