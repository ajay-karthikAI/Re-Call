// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "ScreenCaptureKitAudioTest",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "screencapturekit-audio-test", targets: ["ScreenCaptureKitAudioTest"])
    ],
    targets: [
        .executableTarget(
            name: "ScreenCaptureKitAudioTest",
            linkerSettings: [
                .linkedFramework("AVFoundation"),
                .linkedFramework("CoreGraphics"),
                .linkedFramework("CoreMedia"),
                .linkedFramework("ScreenCaptureKit")
            ]
        )
    ]
)
