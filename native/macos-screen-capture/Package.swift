// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "RecallMacOSCapture",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "recall-macos-capture", targets: ["RecallMacOSCapture"])
    ],
    targets: [
        .executableTarget(
            name: "RecallMacOSCapture",
            linkerSettings: [
                .linkedFramework("AVFoundation"),
                .linkedFramework("CoreGraphics"),
                .linkedFramework("CoreMedia"),
                .linkedFramework("ScreenCaptureKit")
            ]
        )
    ]
)
