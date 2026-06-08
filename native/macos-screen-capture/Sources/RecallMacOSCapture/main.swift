import AVFoundation
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

struct CaptureArguments {
    let apiBaseURL: URL
    let sessionID: String
    let chunkSeconds: Double

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
        return CaptureArguments(apiBaseURL: apiBaseURL, sessionID: sessionID, chunkSeconds: max(2, chunkSeconds))
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

final class ChunkUploader {
    private let uploadURL: URL
    private let sessionID: String

    init(apiBaseURL: URL, sessionID: String) {
        self.uploadURL = apiBaseURL
            .appendingPathComponent("api")
            .appendingPathComponent("recording")
            .appendingPathComponent("chunk")
        self.sessionID = sessionID
    }

    func upload(fileURL: URL) {
        do {
            let body = try multipartBody(fileURL: fileURL)
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
                emit("chunk_uploaded", ["file": fileURL.lastPathComponent])
            }
        } catch {
            emit("upload_error", ["message": error.localizedDescription])
        }
    }

    private func multipartBody(fileURL: URL) throws -> (data: Data, contentType: String) {
        let boundary = "recall-\(UUID().uuidString)"
        var data = Data()

        func append(_ string: String) {
            data.append(Data(string.utf8))
        }

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"session_id\"\r\n\r\n")
        append("\(sessionID)\r\n")

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"source\"\r\n\r\n")
        append("system\r\n")

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
    private let workDirectory: URL
    private let finishGroup = DispatchGroup()

    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var startedAt: CMTime?
    private var outputURL: URL?
    private var chunkIndex = 0

    init(chunkSeconds: Double, uploader: ChunkUploader) {
        self.chunkSeconds = chunkSeconds
        self.uploader = uploader
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
        let url = workDirectory.appendingPathComponent("system-\(chunkIndex).m4a")
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
    }

    private func finishCurrentWriter() {
        guard let writer, let input, let outputURL else {
            return
        }

        self.writer = nil
        self.input = nil
        self.startedAt = nil
        self.outputURL = nil

        finishGroup.enter()
        input.markAsFinished()
        writer.finishWriting { [uploader, finishGroup] in
            if writer.status == .completed {
                uploader.upload(fileURL: outputURL)
            } else if let error = writer.error {
                emit("writer_error", ["message": error.localizedDescription])
            }
            try? FileManager.default.removeItem(at: outputURL)
            finishGroup.leave()
        }
    }
}

final class ScreenAudioCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    private let arguments: CaptureArguments
    private let queue = DispatchQueue(label: "recall.macos.capture.audio")
    private let uploader: ChunkUploader
    private lazy var audioWriter = RotatingAudioWriter(chunkSeconds: arguments.chunkSeconds, uploader: uploader)
    private var stream: SCStream?

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
