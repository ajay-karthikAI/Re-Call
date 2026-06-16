import AVFoundation
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

enum CaptureTestError: LocalizedError {
    case permissionRequired
    case noDisplay
    case writerFailed(String)
    case noAudioCaptured

    var errorDescription: String? {
        switch self {
        case .permissionRequired:
            return "Screen Recording permission is required. Enable it for Terminal in System Settings > Privacy & Security > Screen & System Audio Recording, then rerun this test."
        case .noDisplay:
            return "No display was available to capture."
        case .writerFailed(let message):
            return message
        case .noAudioCaptured:
            return "No audio sample buffers were received. Play audio on the Mac while the 10-second test is running."
        }
    }
}

struct CaptureStats {
    var buffersReceived = 0
    var firstPresentationTime: CMTime?
    var lastPresentationTime: CMTime?

    var capturedDurationSeconds: Double {
        guard let firstPresentationTime, let lastPresentationTime else {
            return 0
        }
        return max(0, CMTimeSubtract(lastPresentationTime, firstPresentationTime).seconds)
    }
}

func log(_ message: String) {
    print("[screencapturekit-audio-test] \(message)")
    fflush(stdout)
}

final class WAVSampleWriter {
    private let outputURL: URL
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var started = false
    private var failed = false

    init(outputURL: URL) {
        self.outputURL = outputURL
    }

    func append(_ sampleBuffer: CMSampleBuffer) throws {
        if failed {
            return
        }
        guard CMSampleBufferDataIsReady(sampleBuffer) else {
            return
        }

        if writer == nil {
            do {
                try startWriter()
            } catch {
                failed = true
                throw error
            }
        }

        guard let writer, let input else {
            return
        }

        if !started {
            let presentationTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            writer.startSession(atSourceTime: presentationTime)
            started = true
        }

        if input.isReadyForMoreMediaData {
            input.append(sampleBuffer)
        }
    }

    func finish() async throws {
        guard let writer, let input else {
            return
        }

        input.markAsFinished()
        try await withCheckedThrowingContinuation { continuation in
            writer.finishWriting {
                if writer.status == .completed {
                    continuation.resume()
                } else {
                    let message = writer.error?.localizedDescription ?? "AVAssetWriter failed with status \(writer.status.rawValue)."
                    continuation.resume(throwing: CaptureTestError.writerFailed(message))
                }
            }
        }
    }

    private func startWriter() throws {
        try? FileManager.default.removeItem(at: outputURL)
        try FileManager.default.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)

        let writer = try AVAssetWriter(outputURL: outputURL, fileType: .wav)
        let input = AVAssetWriterInput(
            mediaType: .audio,
            outputSettings: [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: 48_000,
                AVNumberOfChannelsKey: 2,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsNonInterleaved: false
            ]
        )
        input.expectsMediaDataInRealTime = true

        guard writer.canAdd(input) else {
            throw CaptureTestError.writerFailed("Could not add WAV audio input to AVAssetWriter.")
        }

        writer.add(input)
        guard writer.startWriting() else {
            throw CaptureTestError.writerFailed(writer.error?.localizedDescription ?? "Could not start WAV writer.")
        }

        self.writer = writer
        self.input = input
        log("WAV writer started.")
    }
}

final class ScreenAudioCaptureTest: NSObject, SCStreamOutput, SCStreamDelegate {
    private let outputURL: URL
    private let queue = DispatchQueue(label: "recall.experiments.screencapturekit-audio-test")
    private lazy var sampleWriter = WAVSampleWriter(outputURL: outputURL)
    private var stream: SCStream?
    private var stats = CaptureStats()
    private var writerError: Error?

    init(outputURL: URL) {
        self.outputURL = outputURL
        super.init()
    }

    func run(seconds: UInt64) async throws -> CaptureStats {
        try await start()
        log("Recording for \(seconds) seconds. Play Zoom/Teams/Meet/music audio now.")
        try await Task.sleep(nanoseconds: seconds * 1_000_000_000)
        return try await stop()
    }

    private func start() async throws {
        log("Checking Screen Recording permission.")
        if !CGPreflightScreenCaptureAccess() {
            log("Permission not currently granted. Requesting Screen Recording permission.")
            _ = CGRequestScreenCaptureAccess()
            throw CaptureTestError.permissionRequired
        }
        log("Permission status: granted.")

        log("Loading shareable displays.")
        let content = try await SCShareableContent.current
        guard let display = content.displays.first else {
            throw CaptureTestError.noDisplay
        }
        log("Selected display: \(display.width)x\(display.height), id=\(display.displayID).")

        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let configuration = SCStreamConfiguration()
        configuration.width = 2
        configuration.height = 2
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        configuration.capturesAudio = true
        configuration.excludesCurrentProcessAudio = true
        configuration.sampleRate = 48_000
        configuration.channelCount = 2

        let stream = SCStream(filter: filter, configuration: configuration, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        self.stream = stream

        log("Starting ScreenCaptureKit stream with capturesAudio=true.")
        try await stream.startCapture()
        log("Stream started.")
    }

    private func stop() async throws -> CaptureStats {
        log("Stopping stream.")
        if let stream {
            try await stream.stopCapture()
        }

        return try await withCheckedThrowingContinuation { continuation in
            queue.async { [self] in
                Task {
                    do {
                        try await sampleWriter.finish()
                        if let writerError {
                            throw writerError
                        }
                        if stats.buffersReceived == 0 {
                            throw CaptureTestError.noAudioCaptured
                        }
                        continuation.resume(returning: stats)
                    } catch {
                        continuation.resume(throwing: error)
                    }
                }
            }
        }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        guard outputType == .audio else {
            return
        }

        do {
            try sampleWriter.append(sampleBuffer)
            stats.buffersReceived += 1
            let presentationTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            if stats.firstPresentationTime == nil {
                stats.firstPresentationTime = presentationTime
            }
            stats.lastPresentationTime = presentationTime

            if stats.buffersReceived == 1 || stats.buffersReceived % 50 == 0 {
                log("Audio buffers received: \(stats.buffersReceived)")
            }
        } catch {
            writerError = error
            log("Writer error: \(error.localizedDescription)")
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        writerError = error
        log("Capture error: \(error.localizedDescription)")
    }
}

@main
struct ScreenCaptureKitAudioTest {
    static func main() async {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let outputURL = packageRoot
            .appendingPathComponent("output", isDirectory: true)
            .appendingPathComponent("system-audio-test.wav")

        do {
            log("Output path: \(outputURL.path)")
            let capture = ScreenAudioCaptureTest(outputURL: outputURL)
            let stats = try await capture.run(seconds: 10)
            let attributes = try FileManager.default.attributesOfItem(atPath: outputURL.path)
            let fileSize = attributes[.size] as? NSNumber

            log("Capture complete.")
            log("Audio buffers received: \(stats.buffersReceived)")
            log(String(format: "Duration written: %.2f seconds", stats.capturedDurationSeconds))
            log("WAV file exists: \(FileManager.default.fileExists(atPath: outputURL.path))")
            log("WAV file size: \(fileSize?.intValue ?? 0) bytes")
            log("Output file: \(outputURL.path)")
        } catch {
            log("ERROR: \(error.localizedDescription)")
            exit(1)
        }
    }
}
