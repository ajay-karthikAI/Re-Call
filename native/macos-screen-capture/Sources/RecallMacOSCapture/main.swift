import AVFoundation
import AudioToolbox
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

let systemSilenceRMSThreshold = 0.002
let systemSilencePeakThreshold = 0.012
let minimumUsefulChunkDurationSeconds = 0.35

struct AudioStats {
    let rms: Double
    let peak: Double
    let durationSeconds: Double
    let sampleCount: Int

    var isSilent: Bool {
        sampleCount == 0 ||
            durationSeconds < minimumUsefulChunkDurationSeconds ||
            (rms < systemSilenceRMSThreshold && peak < systemSilencePeakThreshold)
    }
}

struct CaptureArguments {
    let apiBaseURL: URL
    let sessionID: String
    let chunkSeconds: Double
    let recordingStartedAtMs: Double

    static func parse(_ arguments: [String]) throws -> CaptureArguments {
        var values: [String: String] = [:]
        var index = 1
        while index < arguments.count {
            let key = arguments[index]
            if key.hasPrefix("--"), index + 1 < arguments.count {
                values[String(key.dropFirst(2))] = arguments[index + 1]
                index += 2
            } else {
                index += 1
            }
        }

        guard let apiBase = values["api-base"], let apiBaseURL = URL(string: apiBase) else {
            throw CaptureError.invalidArguments("Missing --api-base")
        }
        guard let sessionID = values["session-id"], !sessionID.isEmpty else {
            throw CaptureError.invalidArguments("Missing --session-id")
        }

        let chunkSeconds = Double(values["chunk-seconds"] ?? "6") ?? 6
        let recordingStartedAtMs = Double(values["recording-started-at-ms"] ?? "") ?? nowMilliseconds()
        return CaptureArguments(
            apiBaseURL: apiBaseURL,
            sessionID: sessionID,
            chunkSeconds: max(2, chunkSeconds),
            recordingStartedAtMs: recordingStartedAtMs
        )
    }
}

enum CaptureError: LocalizedError {
    case invalidArguments(String)
    case permissionRequired
    case noDisplay
    case writerFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidArguments(let message):
            return message
        case .permissionRequired:
            return "Screen recording permission is required for ScreenCaptureKit audio."
        case .noDisplay:
            return "No display was available for ScreenCaptureKit capture."
        case .writerFailed(let message):
            return message
        }
    }
}

func emit(_ type: String, _ fields: [String: Any] = [:]) {
    var payload = fields
    payload["type"] = type
    if let data = try? JSONSerialization.data(withJSONObject: payload),
       let line = String(data: data, encoding: .utf8) {
        FileHandle.standardOutput.write(Data((line + "\n").utf8))
    }
}

func nowMilliseconds() -> Double {
    Date().timeIntervalSince1970 * 1000
}

final class ChunkUploader {
    private let uploadURL: URL
    private let sessionID: String

    init(apiBaseURL: URL, sessionID: String) {
        self.uploadURL = apiBaseURL
            .appendingPathComponent("api")
            .appendingPathComponent("recording")
            .appendingPathComponent("system-chunk")
        self.sessionID = sessionID
    }

    func upload(fileURL: URL, chunkIndex: Int, startOffsetMs: Double, endOffsetMs: Double, stats: AudioStats) {
        do {
            let body = try multipartBody(
                fileURL: fileURL,
                chunkIndex: chunkIndex,
                startOffsetMs: startOffsetMs,
                endOffsetMs: endOffsetMs,
                stats: stats
            )
            var request = URLRequest(url: uploadURL)
            request.httpMethod = "POST"
            request.setValue(body.contentType, forHTTPHeaderField: "Content-Type")

            let semaphore = DispatchSemaphore(value: 0)
            var uploadError: Error?
            let task = URLSession.shared.uploadTask(with: request, from: body.data) { _, response, error in
                if let error {
                    uploadError = error
                } else if let httpResponse = response as? HTTPURLResponse, !(200...299).contains(httpResponse.statusCode) {
                    uploadError = CaptureError.writerFailed("Chunk upload failed with HTTP \(httpResponse.statusCode)")
                }
                semaphore.signal()
            }
            task.resume()
            semaphore.wait()

            if let uploadError {
                emit("upload_error", ["message": uploadError.localizedDescription])
            } else {
                let size = (try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? NSNumber)?.intValue ?? 0
                emit(
                    "chunk_uploaded",
                    [
                        "file": fileURL.lastPathComponent,
                        "bytes": size,
                        "chunk_index": chunkIndex,
                        "start_offset_ms": Int(startOffsetMs.rounded()),
                        "end_offset_ms": Int(endOffsetMs.rounded()),
                        "rms": stats.rms,
                        "peak": stats.peak,
                        "duration_seconds": stats.durationSeconds
                    ]
                )
            }
        } catch {
            emit("upload_error", ["message": error.localizedDescription])
        }
    }

    private func multipartBody(
        fileURL: URL,
        chunkIndex: Int,
        startOffsetMs: Double,
        endOffsetMs: Double,
        stats: AudioStats
    ) throws -> (data: Data, contentType: String) {
        let boundary = "recall-\(UUID().uuidString)"
        var data = Data()

        func append(_ string: String) {
            data.append(Data(string.utf8))
        }

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"session_id\"\r\n\r\n")
        append("\(sessionID)\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"chunk_index\"\r\n\r\n")
        append("\(chunkIndex)\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"start_offset_ms\"\r\n\r\n")
        append("\(Int(startOffsetMs.rounded()))\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"end_offset_ms\"\r\n\r\n")
        append("\(Int(endOffsetMs.rounded()))\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"client_created_at_ms\"\r\n\r\n")
        append("\(Int(nowMilliseconds().rounded()))\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"rms\"\r\n\r\n")
        append("\(stats.rms)\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"peak\"\r\n\r\n")
        append("\(stats.peak)\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"duration_seconds\"\r\n\r\n")
        append("\(stats.durationSeconds)\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"silent\"\r\n\r\n")
        append("\(stats.isSilent ? "true" : "false")\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"audio\"; filename=\"\(fileURL.lastPathComponent)\"\r\n")
        append("Content-Type: audio/mp4\r\n\r\n")
        data.append(try Data(contentsOf: fileURL))
        append("\r\n")

        append("--\(boundary)--\r\n")
        return (data, "multipart/form-data; boundary=\(boundary)")
    }
}

final class RotatingAudioWriter {
    private let chunkSeconds: Double
    private let uploader: ChunkUploader
    private let recordingStartedAtMs: Double
    private let workDirectory: URL
    private let finishGroup = DispatchGroup()

    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var startedAt: CMTime?
    private var outputURL: URL?
    private var outputChunkIndex: Int?
    private var outputStartOffsetMs: Double?
    private var chunkIndex = 0

    init(chunkSeconds: Double, uploader: ChunkUploader, recordingStartedAtMs: Double) {
        self.chunkSeconds = chunkSeconds
        self.uploader = uploader
        self.recordingStartedAtMs = recordingStartedAtMs
        self.workDirectory = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("recall-macos-capture-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: workDirectory, withIntermediateDirectories: true)
    }

    func append(_ sampleBuffer: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sampleBuffer) else {
            return
        }

        let presentationTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        if let startedAt, CMTimeSubtract(presentationTime, startedAt).seconds >= chunkSeconds {
            finishCurrentWriter()
        }

        if writer == nil {
            do {
                try startWriter(at: presentationTime)
            } catch {
                emit("writer_error", ["message": error.localizedDescription])
                return
            }
        }

        guard let input, input.isReadyForMoreMediaData else {
            return
        }
        input.append(sampleBuffer)
    }

    func finishAndWait() {
        finishCurrentWriter()
        finishGroup.wait()
        try? FileManager.default.removeItem(at: workDirectory)
    }

    private func startWriter(at presentationTime: CMTime) throws {
        let activeChunkIndex = chunkIndex
        let url = workDirectory.appendingPathComponent("system-\(activeChunkIndex).m4a")
        chunkIndex += 1

        let writer = try AVAssetWriter(outputURL: url, fileType: .m4a)
        let audioInput = AVAssetWriterInput(
            mediaType: .audio,
            outputSettings: [
                AVFormatIDKey: kAudioFormatMPEG4AAC,
                AVSampleRateKey: 48_000,
                AVNumberOfChannelsKey: 2,
                AVEncoderBitRateKey: 128_000
            ]
        )
        audioInput.expectsMediaDataInRealTime = true

        guard writer.canAdd(audioInput) else {
            throw CaptureError.writerFailed("Could not add audio input to AVAssetWriter.")
        }

        writer.add(audioInput)
        guard writer.startWriting() else {
            throw CaptureError.writerFailed(writer.error?.localizedDescription ?? "Could not start audio writer.")
        }
        writer.startSession(atSourceTime: presentationTime)

        self.writer = writer
        self.input = audioInput
        self.startedAt = presentationTime
        self.outputURL = url
        self.outputChunkIndex = activeChunkIndex
        self.outputStartOffsetMs = max(0, nowMilliseconds() - recordingStartedAtMs)
    }

    private func finishCurrentWriter() {
        guard let writer, let input, let outputURL else {
            return
        }
        let chunkIndex = outputChunkIndex ?? 0
        let startOffsetMs = outputStartOffsetMs ?? max(0, nowMilliseconds() - recordingStartedAtMs)
        let endOffsetMs = max(startOffsetMs, nowMilliseconds() - recordingStartedAtMs)

        self.writer = nil
        self.input = nil
        self.startedAt = nil
        self.outputURL = nil
        self.outputChunkIndex = nil
        self.outputStartOffsetMs = nil

        finishGroup.enter()
        input.markAsFinished()
        writer.finishWriting { [uploader, finishGroup] in
            if writer.status == .completed {
                let stats = calculateAudioStats(fileURL: outputURL)
                if stats.isSilent {
                    emit(
                        "chunk_skipped",
                        [
                            "file": outputURL.lastPathComponent,
                            "chunk_index": chunkIndex,
                            "start_offset_ms": Int(startOffsetMs.rounded()),
                            "end_offset_ms": Int(endOffsetMs.rounded()),
                            "reason": "silent_system_audio",
                            "rms": stats.rms,
                            "peak": stats.peak,
                            "duration_seconds": stats.durationSeconds
                        ]
                    )
                } else {
                    uploader.upload(
                        fileURL: outputURL,
                        chunkIndex: chunkIndex,
                        startOffsetMs: startOffsetMs,
                        endOffsetMs: endOffsetMs,
                        stats: stats
                    )
                }
            } else if let error = writer.error {
                emit("writer_error", ["message": error.localizedDescription])
            }
            try? FileManager.default.removeItem(at: outputURL)
            finishGroup.leave()
        }
    }
}

func calculateAudioStats(fileURL: URL) -> AudioStats {
    let asset = AVURLAsset(url: fileURL)
    guard let track = asset.tracks(withMediaType: .audio).first,
          let reader = try? AVAssetReader(asset: asset) else {
        return AudioStats(rms: 0, peak: 0, durationSeconds: 0, sampleCount: 0)
    }

    let output = AVAssetReaderTrackOutput(
        track: track,
        outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false
        ]
    )
    output.alwaysCopiesSampleData = false

    guard reader.canAdd(output) else {
        return AudioStats(rms: 0, peak: 0, durationSeconds: CMTimeGetSeconds(asset.duration), sampleCount: 0)
    }

    reader.add(output)
    guard reader.startReading() else {
        return AudioStats(rms: 0, peak: 0, durationSeconds: CMTimeGetSeconds(asset.duration), sampleCount: 0)
    }

    var sumSquares = 0.0
    var peak = 0.0
    var sampleCount = 0

    while let sampleBuffer = output.copyNextSampleBuffer() {
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else {
            continue
        }

        var totalLength = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        let status = CMBlockBufferGetDataPointer(
            blockBuffer,
            atOffset: 0,
            lengthAtOffsetOut: nil,
            totalLengthOut: &totalLength,
            dataPointerOut: &dataPointer
        )
        guard status == kCMBlockBufferNoErr, let dataPointer else {
            continue
        }

        let floatCount = totalLength / MemoryLayout<Float>.size
        dataPointer.withMemoryRebound(to: Float.self, capacity: floatCount) { samples in
            for index in 0..<floatCount {
                let value = Double(samples[index])
                sumSquares += value * value
                peak = max(peak, abs(value))
            }
        }
        sampleCount += floatCount
    }

    let rms = sampleCount > 0 ? sqrt(sumSquares / Double(sampleCount)) : 0
    let durationSeconds = max(0, CMTimeGetSeconds(asset.duration))
    return AudioStats(rms: rms, peak: peak, durationSeconds: durationSeconds, sampleCount: sampleCount)
}

final class ScreenAudioCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    private let arguments: CaptureArguments
    private let queue = DispatchQueue(label: "recall.macos.capture.audio")
    private let uploader: ChunkUploader
    private lazy var audioWriter = RotatingAudioWriter(
        chunkSeconds: arguments.chunkSeconds,
        uploader: uploader,
        recordingStartedAtMs: arguments.recordingStartedAtMs
    )
    private var stream: SCStream?
    private var audioBuffersReceived = 0

    init(arguments: CaptureArguments) {
        self.arguments = arguments
        self.uploader = ChunkUploader(apiBaseURL: arguments.apiBaseURL, sessionID: arguments.sessionID)
        super.init()
    }

    func start() async throws {
        if !CGPreflightScreenCaptureAccess() {
            _ = CGRequestScreenCaptureAccess()
            throw CaptureError.permissionRequired
        }

        let content = try await SCShareableContent.current
        guard let display = content.displays.first else {
            throw CaptureError.noDisplay
        }

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
        try await stream.startCapture()
        emit("started", ["session_id": arguments.sessionID])
    }

    func stop() async {
        if let stream {
            try? await stream.stopCapture()
        }
        queue.sync {
            audioWriter.finishAndWait()
        }
        emit("stopped", ["session_id": arguments.sessionID])
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        guard outputType == .audio else {
            return
        }
        audioBuffersReceived += 1
        if audioBuffersReceived == 1 || audioBuffersReceived % 50 == 0 {
            emit("audio_buffer", ["buffers": audioBuffersReceived])
        }
        audioWriter.append(sampleBuffer)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        emit("capture_error", ["message": error.localizedDescription])
    }
}

@main
struct RecallMacOSCapture {
    static func main() async {
        do {
            let arguments = try CaptureArguments.parse(CommandLine.arguments)
            let capture = ScreenAudioCapture(arguments: arguments)

            let stopTask = Task.detached {
                while let line = readLine() {
                    if line.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "stop" {
                        return
                    }
                }
            }

            try await capture.start()
            await stopTask.value
            await capture.stop()
        } catch {
            emit("error", ["message": error.localizedDescription])
            exit(1)
        }
    }
}
