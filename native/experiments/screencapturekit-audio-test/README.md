# ScreenCaptureKit Audio Test

Standalone proof-of-concept for capturing macOS system/display audio with ScreenCaptureKit.

This experiment is intentionally separate from the Re: Call Electron app and backend.

## Build

```bash
swift build
```

## Run

```bash
swift run screencapturekit-audio-test
```

The test records for 10 seconds and writes:

```text
output/system-audio-test.wav
```

Play audio on the Mac while it runs. If macOS blocks capture, enable Screen Recording / Screen & System Audio Recording permission for Terminal, then rerun the test.
