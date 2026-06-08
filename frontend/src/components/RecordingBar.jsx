import { LoaderCircle, Mic, Square, X } from "lucide-react";

function formatTime(totalSeconds) {
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function RecordingBar({ status, elapsedSeconds, error, audioLevel = 0, audioWarning = "", onStart, onStop, onCancel, activeMeeting, exportButton }) {
  const isRecording = status === "recording";
  const isStarting = status === "starting";
  const isBusy = ["starting", "stopping"].includes(status);
  const meterLevel = Math.min(1, audioLevel * 18);

  return (
    <header className="recording-bar">
      <div className="recording-meta">
        <div className="brand-compact">
          <span className="brand-mark">R:</span>
          <span>Re: Call</span>
        </div>
        <div className={`status-pill status-${status}`}>
          {isBusy ? <LoaderCircle size={14} className="spin" /> : null}
          <span>{status}</span>
        </div>
        <span className="timer">{formatTime(elapsedSeconds)}</span>
        {isRecording ? (
          <div className="mic-meter" title="Microphone input level">
            <span style={{ transform: `scaleX(${meterLevel})` }} />
          </div>
        ) : null}
        {activeMeeting ? <span className="active-title">{activeMeeting.title}</span> : null}
      </div>

      <div className="recording-actions">
        {audioWarning ? <span className="warning-text">{audioWarning}</span> : null}
        {error ? <span className="error-text">{error}</span> : null}
        {exportButton}
        {isRecording ? (
          <button className="danger-button" onClick={onStop} title="Stop recording">
            <Square size={16} />
            <span>Stop</span>
          </button>
        ) : isStarting ? (
          <button className="danger-button" onClick={onCancel} title="Cancel recording start">
            <X size={16} />
            <span>Cancel</span>
          </button>
        ) : (
          <button className="primary-button" onClick={onStart} disabled={isBusy} title="Start recording">
            {isBusy ? <LoaderCircle size={16} className="spin" /> : <Mic size={16} />}
            <span>Start</span>
          </button>
        )}
      </div>
    </header>
  );
}
