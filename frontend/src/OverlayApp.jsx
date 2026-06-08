import { FileText, LoaderCircle, Mic, Minus, Presentation, ScrollText, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { useRecorder } from "./hooks/useRecorder.js";

const FALLBACK_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const EXPORT_OPTIONS = [
  { format: "pptx", label: "PPT", Icon: Presentation },
  { format: "pdf", label: "PDF", Icon: FileText },
  { format: "markdown", label: "MD", Icon: ScrollText },
];

function formatTime(totalSeconds) {
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function downloadUrl(url, filename) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "";
  link.rel = "noopener noreferrer";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function getMeetingTitle() {
  const now = new Date();
  return `Desktop meeting ${new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(now)}`;
}

export default function OverlayApp() {
  const [apiBaseUrl, setApiBaseUrl] = useState(FALLBACK_API_BASE);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [meeting, setMeeting] = useState(null);
  const [exportingFormat, setExportingFormat] = useState("");
  const [exportError, setExportError] = useState("");

  useEffect(() => {
    document.body.classList.add("overlay-body");
    window.recall?.getApiBaseUrl?.().then(setApiBaseUrl).catch(() => setApiBaseUrl(FALLBACK_API_BASE));
    return () => {
      document.body.classList.remove("overlay-body");
    };
  }, []);

  const recorder = useRecorder({
    apiBaseUrl,
    getStartPayload: () => ({
      title: getMeetingTitle(),
      platform: "Desktop overlay",
    }),
    startTimeoutMs: 30000,
    onSessionStarted: setActiveSessionId,
    onProcessingStarted: setActiveSessionId,
  });

  useEffect(() => {
    if (!activeSessionId || recorder.status !== "processing" || ["complete", "error"].includes(meeting?.status)) {
      return undefined;
    }

    let cancelled = false;
    async function loadMeeting() {
      try {
        const response = await fetch(`${apiBaseUrl}/api/meetings/${activeSessionId}`);
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        if (!cancelled) {
          setMeeting(data);
        }
      } catch {
        // Keep polling; transient backend misses are common while workers start.
      }
    }

    loadMeeting();
    const timer = window.setInterval(loadMeeting, 4500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSessionId, apiBaseUrl, meeting?.status, recorder.status]);

  function resetOverlayRecording() {
    recorder.cancel();
    setMeeting(null);
    setActiveSessionId(null);
    setExportError("");
  }

  async function exportMeeting(format) {
    if (!activeSessionId) {
      return;
    }

    setExportingFormat(format);
    setExportError("");
    try {
      const response = await fetch(`${apiBaseUrl}/api/export/${activeSessionId}?format=${format}`, { method: "POST" });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Export failed");
      }
      const data = await response.json();
      const url = data.download_url || data.pptx_url;
      if (!url) {
        throw new Error("Export finished, but no download URL was returned.");
      }
      downloadUrl(url, data.filename);
    } catch (error) {
      setExportError(error.message);
    } finally {
      setExportingFormat("");
    }
  }

  const isReady = meeting?.status === "complete";
  const hasProcessingError = meeting?.status === "error";
  const isProcessing = recorder.status === "processing" && !isReady;
  const isStarting = recorder.status === "starting";
  const isRecording = recorder.status === "recording";
  const isStopping = recorder.status === "stopping";
  const error = recorder.error || exportError || meeting?.notes_json?.error || "";
  const meterLevel = Math.min(1, recorder.audioLevel * 18);

  return (
    <main className="overlay-shell">
      <div className="overlay-drag-row">
        <div className="overlay-brand">
          <span className="brand-mark">R:</span>
          <div>
            <strong>Re: Call</strong>
            <small>Visible desktop overlay</small>
          </div>
        </div>
        <button className="overlay-icon-button" onClick={() => window.recall?.minimizeOverlayWindow?.()} title="Minimize overlay">
          <Minus size={15} />
        </button>
      </div>

      <section className="overlay-panel">
        {isReady ? (
          <>
            <div className="overlay-status-row">
              <span className="status-light complete" />
              <div>
                <h1>Meeting ready</h1>
                <p>Choose how to export the transcript and notes.</p>
              </div>
            </div>
            <div className="overlay-export-grid">
              {EXPORT_OPTIONS.map(({ format, label, Icon }) => (
                <button
                  key={format}
                  className="overlay-export-button"
                  onClick={() => exportMeeting(format)}
                  disabled={Boolean(exportingFormat)}
                  title={`Export as ${label}`}
                >
                  {exportingFormat === format ? <LoaderCircle size={16} className="spin" /> : <Icon size={16} />}
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </>
        ) : hasProcessingError ? (
          <>
            <div className="overlay-status-row">
              <span className="status-light error" />
              <div>
                <h1>Processing failed</h1>
                <p>Re: Call could not finish this meeting.</p>
              </div>
            </div>
            <div className="overlay-error">{error || "Check the backend and Celery terminals, then try again."}</div>
            <button className="overlay-secondary-button" onClick={resetOverlayRecording}>
              Try again
            </button>
          </>
        ) : isRecording || isStopping ? (
          <>
            <div className="overlay-status-row">
              <span className="status-light recording" />
              <div>
                <h1>{isStopping ? "Saving audio" : "Recording"}</h1>
                <p>{formatTime(recorder.elapsedSeconds)}</p>
              </div>
            </div>
            <div className="mic-meter overlay-mic-meter" title="Microphone input level">
              <span style={{ transform: `scaleX(${meterLevel})` }} />
            </div>
            {recorder.audioWarning ? <div className="overlay-warning">{recorder.audioWarning}</div> : null}
            <button className="overlay-danger-button" onClick={recorder.stop} disabled={isStopping}>
              {isStopping ? <LoaderCircle size={16} className="spin" /> : <Square size={16} />}
              <span>{isStopping ? "Stopping" : "Stop recording"}</span>
            </button>
          </>
        ) : isProcessing || isStarting ? (
          <>
            <div className="overlay-status-row">
              <span className="status-light waiting" />
              <div>
                <h1>{isStarting ? "Starting" : "Transcribing"}</h1>
                <p>{isStarting ? "Grant audio permissions when prompted." : "Waiting for notes and exports."}</p>
              </div>
            </div>
            <div className="overlay-loading-line">
              <LoaderCircle size={16} className="spin" />
              <span>{isStarting ? "Preparing capture" : "Processing meeting"}</span>
            </div>
            {isStarting ? (
              <button className="overlay-secondary-button" onClick={recorder.cancel}>
                Cancel
              </button>
            ) : null}
          </>
        ) : (
          <>
            <div className="overlay-status-row">
              <span className="status-light idle" />
              <div>
                <h1>Record this meeting?</h1>
                <p>Captures microphone audio with permission.</p>
              </div>
            </div>
            {error ? <div className="overlay-error">{error}</div> : null}
            <button className="overlay-primary-button" onClick={recorder.start}>
              <Mic size={16} />
              <span>Start recording</span>
            </button>
          </>
        )}
      </section>

      <footer className="overlay-footer">
        <button onClick={() => window.recall?.showMainWindow?.()}>Dashboard</button>
        <span>{activeSessionId ? "Session active" : "Always on top"}</span>
      </footer>
    </main>
  );
}
