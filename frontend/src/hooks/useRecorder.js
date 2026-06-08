import { useCallback, useEffect, useRef, useState } from "react";

const START_TIMEOUT_MS = 12000;
const CHUNK_TIMEOUT_MS = 20000;
const SILENCE_RMS_THRESHOLD = 0.012;

function stopStream(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

function timeoutMessage(label) {
  return `${label} timed out. Check the backend, microphone permission, and try again.`;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = START_TIMEOUT_MS, label = "Request") {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) {
      throw new Error(`${label} failed (${response.status})`);
    }
    return response;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(timeoutMessage(label));
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function getRecorderOptions() {
  if (!window.MediaRecorder) {
    throw new Error("This browser does not support audio recording.");
  }

  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  const mimeType = candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate));
  return mimeType ? { mimeType } : undefined;
}

async function getMicrophoneStream() {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone recording requires a browser with media device support.");
  }
  return navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: true,
    },
  });
}

function createAudioMonitor(stream, onLevel) {
  if (!window.AudioContext && !window.webkitAudioContext) {
    return null;
  }

  const AudioContextConstructor = window.AudioContext || window.webkitAudioContext;
  const context = new AudioContextConstructor();
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  const source = context.createMediaStreamSource(stream);
  source.connect(analyser);
  const data = new Uint8Array(analyser.fftSize);
  const stats = {
    samples: 0,
    silentSamples: 0,
    maxRms: 0,
    rmsTotal: 0,
  };

  const timer = window.setInterval(() => {
    analyser.getByteTimeDomainData(data);
    let sumSquares = 0;
    for (const value of data) {
      const normalized = (value - 128) / 128;
      sumSquares += normalized * normalized;
    }
    const rms = Math.sqrt(sumSquares / data.length);
    stats.samples += 1;
    stats.rmsTotal += rms;
    stats.maxRms = Math.max(stats.maxRms, rms);
    if (rms < SILENCE_RMS_THRESHOLD) {
      stats.silentSamples += 1;
    }
    onLevel?.(rms, getAudioDiagnostics(stats));
  }, 250);

  return {
    getDiagnostics: () => getAudioDiagnostics(stats),
    stop: async () => {
      window.clearInterval(timer);
      source.disconnect();
      await context.close().catch(() => {});
    },
  };
}

function getAudioDiagnostics(stats) {
  const averageRms = stats.samples ? stats.rmsTotal / stats.samples : 0;
  const silentRatio = stats.samples ? stats.silentSamples / stats.samples : 1;
  return {
    mic_average_rms: Number(averageRms.toFixed(5)),
    mic_max_rms: Number(stats.maxRms.toFixed(5)),
    mic_silent_ratio: Number(silentRatio.toFixed(3)),
    mic_level_samples: stats.samples,
    mic_likely_silent: stats.samples >= 8 && stats.maxRms < SILENCE_RMS_THRESHOLD,
  };
}

export function useRecorder({
  apiBaseUrl,
  onSessionStarted,
  onProcessingStarted,
  getAudioStream = getMicrophoneStream,
  getStartPayload,
  startTimeoutMs = START_TIMEOUT_MS,
}) {
  const [status, setStatus] = useState("idle");
  const [sessionId, setSessionId] = useState(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState("");
  const [audioLevel, setAudioLevel] = useState(0);
  const [audioWarning, setAudioWarning] = useState("");
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const audioMonitorRef = useRef(null);
  const audioDiagnosticsRef = useRef(null);
  const startedAtRef = useRef(null);
  const uploadPromisesRef = useRef([]);
  const startAttemptRef = useRef(0);

  useEffect(() => {
    if (status !== "recording") {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAtRef.current) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [status]);

  const uploadChunk = useCallback(
    async (activeSessionId, blob) => {
      if (!blob.size) {
        return;
      }
      const formData = new FormData();
      formData.append("session_id", activeSessionId);
      formData.append("audio", blob, `chunk-${Date.now()}.webm`);
      const upload = fetchWithTimeout(
        `${apiBaseUrl}/api/recording/chunk`,
        { method: "POST", body: formData },
        CHUNK_TIMEOUT_MS,
        "Audio upload"
      );
      uploadPromisesRef.current.push(upload);
      await upload;
    },
    [apiBaseUrl]
  );

  const cancel = useCallback(() => {
    startAttemptRef.current += 1;
    const recorder = mediaRecorderRef.current;

    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        // The recorder may already be stopping; the stream cleanup below is enough.
      }
    }

    stopStream(streamRef.current);
    audioMonitorRef.current?.stop?.();
    audioMonitorRef.current = null;
    audioDiagnosticsRef.current = null;
    mediaRecorderRef.current = null;
    streamRef.current = null;
    startedAtRef.current = null;
    uploadPromisesRef.current = [];
    setElapsedSeconds(0);
    setAudioLevel(0);
    setAudioWarning("");
    setSessionId(null);
    setStatus("idle");
  }, []);

  const start = useCallback(async () => {
    const attemptId = startAttemptRef.current + 1;
    startAttemptRef.current = attemptId;
    setError("");
    setAudioLevel(0);
    setAudioWarning("");
    setStatus("starting");
    let stream = null;
    let startSettled = false;

    try {
      const capturePromise = getAudioStream().then((nextStream) => {
        if (startSettled || attemptId !== startAttemptRef.current) {
          stopStream(nextStream);
        }
        return nextStream;
      });

      stream = await Promise.race([
        capturePromise,
        new Promise((_, reject) =>
          window.setTimeout(() => {
            startSettled = true;
            reject(new Error(timeoutMessage("Audio permission")));
          }, startTimeoutMs)
        ),
      ]);
      startSettled = true;

      if (attemptId !== startAttemptRef.current) {
        stopStream(stream);
        return;
      }

      const startPayload = getStartPayload?.() || null;
      const response = await fetchWithTimeout(
        `${apiBaseUrl}/api/recording/start`,
        startPayload
          ? {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(startPayload),
            }
          : { method: "POST" },
        startTimeoutMs,
        "Recording session"
      );
      const data = await response.json();
      const recorder = new MediaRecorder(stream, getRecorderOptions());
      const audioMonitor = createAudioMonitor(stream, (level, diagnostics) => {
        audioDiagnosticsRef.current = diagnostics;
        setAudioLevel(level);
        if (diagnostics.mic_likely_silent) {
          setAudioWarning("Mic input looks silent. Check the selected microphone, mute switch, and macOS microphone permission.");
        } else if (diagnostics.mic_max_rms >= SILENCE_RMS_THRESHOLD) {
          setAudioWarning("");
        }
      });

      recorder.ondataavailable = (event) => {
        uploadChunk(data.session_id, event.data).catch((chunkError) => {
          setError(chunkError.message);
        });
      };

      streamRef.current = stream;
      audioMonitorRef.current = audioMonitor;
      mediaRecorderRef.current = recorder;
      startedAtRef.current = Date.now();
      uploadPromisesRef.current = [];
      setElapsedSeconds(0);
      setSessionId(data.session_id);
      setStatus("recording");
      onSessionStarted?.(data.session_id);
      recorder.start(6000);
    } catch (recordingError) {
      stopStream(stream);
      audioMonitorRef.current?.stop?.();
      audioMonitorRef.current = null;
      if (attemptId !== startAttemptRef.current) {
        return;
      }
      setStatus("idle");
      setError(recordingError.message);
    }
  }, [apiBaseUrl, getAudioStream, getStartPayload, onSessionStarted, startTimeoutMs, uploadChunk]);

  const stop = useCallback(async () => {
    if (!sessionId || !mediaRecorderRef.current) {
      return;
    }

    setStatus("stopping");
    const duration = Math.max(0, Math.floor((Date.now() - startedAtRef.current) / 1000));

    await new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === "inactive") {
        resolve();
        return;
      }
      recorder.addEventListener("stop", resolve, { once: true });
      try {
        recorder.requestData();
        recorder.stop();
      } catch {
        resolve();
      }
    });

    stopStream(streamRef.current);
    const audioDiagnostics = audioDiagnosticsRef.current || audioMonitorRef.current?.getDiagnostics?.() || null;
    await audioMonitorRef.current?.stop?.();
    audioMonitorRef.current = null;
    await Promise.allSettled(uploadPromisesRef.current);

    try {
      await fetchWithTimeout(
        `${apiBaseUrl}/api/recording/stop`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, duration_seconds: duration, capture_diagnostics: audioDiagnostics }),
        },
        startTimeoutMs,
        "Stop recording"
      );
      setStatus("processing");
      onProcessingStarted?.(sessionId);
    } catch (stopError) {
      setStatus("idle");
      setError(stopError.message);
    }
  }, [apiBaseUrl, onProcessingStarted, sessionId, startTimeoutMs]);

  return {
    status,
    sessionId,
    elapsedSeconds,
    error,
    audioLevel,
    audioWarning,
    start,
    stop,
    cancel,
  };
}
