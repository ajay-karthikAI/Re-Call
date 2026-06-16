import {
  AlertTriangle,
  BarChart3,
  Download,
  FileText,
  LayoutDashboard,
  Lightbulb,
  ListChecks,
  LoaderCircle,
  Mic,
  Minus,
  Presentation,
  ScrollText,
  Square,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ChartCard, getStructuredChartCards } from "./components/ChartCard.jsx";
import { ReCallLogo } from "./components/ReCallLogo.jsx";
import { OverlayAskBar } from "./components/overlay/OverlayAskBar.jsx";
import { OverlayFeed } from "./components/overlay/OverlayFeed.jsx";
import { useRecorder } from "./hooks/useRecorder.js";
import { useWebSocket } from "./hooks/useWebSocket.js";

const FALLBACK_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const EXPORT_OPTIONS = [
  { format: "pptx", label: "PPT", Icon: Presentation },
  { format: "pdf", label: "PDF", Icon: FileText },
  { format: "markdown", label: "MD", Icon: ScrollText },
];

function asTextList(items = []) {
  return items
    .map((item) => (typeof item === "string" ? item : item?.text || item?.question || item?.task || item?.objective || ""))
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

function actionText(item) {
  if (typeof item === "string") {
    return { owner: "TBD", task: item, due: "TBD" };
  }
  return {
    owner: item?.owner || item?.speaker || "TBD",
    task: item?.task || item?.text || "Follow up",
    due: item?.due || "TBD",
  };
}

function dedupeSuggestedAnswers(items = []) {
  const seen = new Set();
  const answers = [];
  items.forEach((item) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const question = String(item.question || "").trim();
    const answer = String(item.answer || item.text || "").trim();
    const key = question.toLowerCase().replace(/\s+/g, " ");
    if (!question || !answer || seen.has(key)) {
      return;
    }
    seen.add(key);
    answers.push({ ...item, question, answer });
  });
  return answers;
}

function getRecordingInsightState(meeting) {
  const notes = meeting?.notes_json || {};
  const memory = notes.live_memory || {};
  const insights = notes.live_insights || {};
  const overlayCards = Array.isArray(insights.overlay_cards) ? insights.overlay_cards : [];
  const answerCards = overlayCards.filter((card) => card?.type !== "chart");

  return {
    questions: insights.questions?.length ? asTextList(insights.questions) : asTextList(memory.questions),
    suggestedAnswers: dedupeSuggestedAnswers([...answerCards, ...(insights.suggested_answers || [])]),
    actionItems: insights.action_items?.length ? insights.action_items : memory.actions || [],
    chartCards: getStructuredChartCards(notes),
    risks: asTextList(insights.risks),
    objectives: asTextList(insights.objectives || insights.goals || insights.decisions),
    summary: insights.live_summary || memory.summary || "",
  };
}

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

function RecordingInsightCard({ title, icon: Icon, children }) {
  return (
    <article className="overlay-live-card">
      <div className="overlay-live-card-header">
        <Icon size={15} />
        <h2>{title}</h2>
      </div>
      <div className="overlay-live-card-body">{children}</div>
    </article>
  );
}

function RecordingInsightGrid({ meeting }) {
  const insights = getRecordingInsightState(meeting);
  const firstAnswer = insights.suggestedAnswers[0];
  const objectiveItems = insights.objectives.length
    ? insights.objectives
    : insights.summary
      ? [insights.summary]
      : [];

  return (
    <section className="overlay-recording-popups" aria-label="Live recording popups">
      <RecordingInsightCard title="Questions + Answers" icon={Lightbulb}>
        {firstAnswer ? (
          <div className="overlay-qa-block">
            <strong>{firstAnswer.question}</strong>
            <p>{firstAnswer.answer}</p>
          </div>
        ) : null}
        {insights.questions.length ? (
          <ul className="overlay-popup-list">
            {insights.questions.slice(0, firstAnswer ? 2 : 4).map((question, index) => (
              <li key={`${question}-${index}`}>{question}</li>
            ))}
          </ul>
        ) : !firstAnswer ? (
          <p className="overlay-popup-empty">Listening for questions and suggested answers.</p>
        ) : null}
      </RecordingInsightCard>

      <RecordingInsightCard title="Live Charts" icon={BarChart3}>
        {insights.chartCards.length ? (
          <div className="overlay-popup-chart">
            <strong>{insights.chartCards[0].title || "Live chart"}</strong>
            <ChartCard card={insights.chartCards[0]} compact />
          </div>
        ) : (
          <p className="overlay-popup-empty">Charts appear when Re: Call hears graphable data.</p>
        )}
      </RecordingInsightCard>

      <RecordingInsightCard title="Action Items" icon={ListChecks}>
        {insights.actionItems.length ? (
          <div className="overlay-popup-actions">
            {insights.actionItems.slice(0, 4).map((item, index) => {
              const action = actionText(item);
              return (
                <div key={`${action.task}-${index}`}>
                  <span>{action.owner}</span>
                  <strong>{action.task}</strong>
                  <small>{action.due}</small>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="overlay-popup-empty">Next steps will collect here as they are mentioned.</p>
        )}
      </RecordingInsightCard>

      <RecordingInsightCard title="Risks + Objectives" icon={AlertTriangle}>
        {insights.risks.length || objectiveItems.length ? (
          <div className="overlay-risk-objective-grid">
            {insights.risks.length ? (
              <div>
                <span>Risks</span>
                <ul className="overlay-popup-list">
                  {insights.risks.slice(0, 3).map((risk, index) => (
                    <li key={`${risk}-${index}`}>{risk}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {objectiveItems.length ? (
              <div>
                <span>Objectives</span>
                <ul className="overlay-popup-list">
                  {objectiveItems.slice(0, 2).map((objective, index) => (
                    <li key={`${objective}-${index}`}>{objective}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : (
          <p className="overlay-popup-empty">Risks, blockers, and objectives will appear here.</p>
        )}
      </RecordingInsightCard>
    </section>
  );
}

export default function OverlayApp() {
  const [apiBaseUrl, setApiBaseUrl] = useState(FALLBACK_API_BASE);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [meeting, setMeeting] = useState(null);
  const [exportingFormat, setExportingFormat] = useState("");
  const [exportError, setExportError] = useState("");
  const [systemAudioStatus, setSystemAudioStatus] = useState({ enabled: false, available: false });
  const [localOverlayCards, setLocalOverlayCards] = useState([]);

  useEffect(() => {
    document.documentElement.classList.add("overlay-document");
    document.body.classList.add("overlay-body");
    window.recall?.getApiBaseUrl?.().then(setApiBaseUrl).catch(() => setApiBaseUrl(FALLBACK_API_BASE));
    window.recall?.systemAudioStatus?.().then(setSystemAudioStatus).catch(() => setSystemAudioStatus({ enabled: false, available: false }));
    return () => {
      document.documentElement.classList.remove("overlay-document");
      document.body.classList.remove("overlay-body");
    };
  }, []);

  const startSystemCapture = useCallback(
    async (sessionId, options = {}) => {
      if (!systemAudioStatus.enabled || !window.recall?.startSystemAudio) {
        return null;
      }

      const result = await window.recall.startSystemAudio({
        apiBaseUrl,
        sessionId,
        chunkSeconds: 6,
        recordingStartedAtMs: options.recordingStartedAtMs,
      });
      const diagnostics = result?.diagnostics || {
        system_audio_enabled: true,
        system_audio_started: false,
      };

      if (!result?.started) {
        return {
          diagnostics,
          warning: result?.detail || "System audio unavailable. Continuing with microphone only.",
        };
      }

      return {
        diagnostics,
        stop: () => window.recall?.stopSystemAudio?.(),
      };
    },
    [apiBaseUrl, systemAudioStatus.enabled]
  );

  const handleSessionStarted = useCallback((sessionId) => {
    setActiveSessionId(sessionId);
    setMeeting({
      id: sessionId,
      title: getMeetingTitle(),
      status: "recording",
      transcript: "",
      notes_json: null,
      duration_seconds: 0,
    });
  }, []);

  const handleProcessingStarted = useCallback((sessionId) => {
    setActiveSessionId(sessionId);
    setMeeting((current) => (current?.id === sessionId ? { ...current, status: "transcribing" } : current));
  }, []);

  const recorder = useRecorder({
    apiBaseUrl,
    getStartPayload: () => ({
      title: getMeetingTitle(),
      platform: "Desktop overlay",
    }),
    startTimeoutMs: 30000,
    onSessionStarted: handleSessionStarted,
    onProcessingStarted: handleProcessingStarted,
    startSystemAudioCapture: systemAudioStatus.enabled ? startSystemCapture : undefined,
  });

  const handleSocketMessage = useCallback((message) => {
    if (!message?.session_id || message.session_id !== activeSessionId) {
      return;
    }

    if (message.type === "live_transcript") {
      setMeeting((current) => {
        if (!current || current.id !== message.session_id) {
          return current;
        }
        return {
          ...current,
          transcript: message.transcript || current.transcript || "",
          notes_json: {
            ...(current.notes_json || {}),
            live_transcript: {
              ...((current.notes_json || {}).live_transcript || {}),
              status: "streaming",
              source: message.source,
              chunk_index: message.chunk_index,
              transcript: message.transcript || current.transcript || "",
            },
            ...(message.memory
              ? {
                  live_memory: {
                    summary: message.memory.summary || "",
                    questions: message.memory.questions || [],
                    actions: message.memory.actions || [],
                    keys: message.memory.keys || {},
                  },
                }
              : {}),
          },
        };
      });
      return;
    }

    if (message.type === "live_insights") {
      setMeeting((current) => {
        if (!current || current.id !== message.session_id) {
          return current;
        }
        return {
          ...current,
          notes_json: {
            ...(current.notes_json || {}),
            live_insights: message.insights || {},
          },
        };
      });
      return;
    }

    if (message.type === "live_insights_error") {
      setMeeting((current) => {
        if (!current || current.id !== message.session_id) {
          return current;
        }
        return {
          ...current,
          notes_json: {
            ...(current.notes_json || {}),
            live_insights_error: message.message || "Live insights update failed.",
          },
        };
      });
    }
  }, [activeSessionId]);

  useWebSocket(apiBaseUrl, activeSessionId, handleSocketMessage);

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
    setLocalOverlayCards([]);
  }

  function handleOverlayAsk(prompt) {
    const createdAt = new Date().toISOString();
    setLocalOverlayCards((current) => [
      {
        id: `local-ask-${createdAt}-${current.length}`,
        type: "ask_response",
        source_type: "local_overlay",
        confidence: "placeholder",
        prompt,
        response: "Ready for backend connection.",
        created_at: createdAt,
      },
      ...current,
    ]);
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
      resetOverlayRecording();
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
  const isRecordingOverlay = isRecording || isStopping;
  const isIdle = !isReady && !hasProcessingError && !isRecording && !isStopping && !isProcessing && !isStarting;
  const error = recorder.error || exportError || meeting?.notes_json?.error || "";
  const isSlimIdle = isIdle && !error;
  const meterLevel = Math.min(1, recorder.audioLevel * 18);

  useEffect(() => {
    const resizePromise = window.recall?.resizeOverlayWindow?.({
      expanded: !isSlimIdle,
      mode: isRecordingOverlay ? "recording" : "standard",
    });
    resizePromise?.catch?.(() => {});
  }, [isRecordingOverlay, isSlimIdle]);

  return (
    <main className={`overlay-shell ${isSlimIdle ? "is-idle" : "is-expanded"} ${isRecordingOverlay ? "is-recording" : ""}`}>
      <div className="overlay-window-actions">
        <button className="overlay-icon-button" onClick={() => window.recall?.minimizeOverlayWindow?.()} title="Minimize overlay" aria-label="Minimize overlay">
          <Minus size={14} />
        </button>
        <button className="overlay-icon-button" onClick={() => window.recall?.hideOverlayWindow?.()} title="Exit overlay" aria-label="Exit overlay">
          <X size={14} />
        </button>
      </div>

      <section className={`overlay-panel ${isIdle ? "overlay-panel-idle" : ""}`}>
        {isIdle ? (
          <>
            <div className="overlay-idle-layout">
              <div className="overlay-left-actions">
                <ReCallLogo className="overlay-logo" />
                <button className="overlay-dashboard-button" onClick={() => window.recall?.showMainWindow?.()}>
                  <LayoutDashboard size={16} />
                  <span>Dashboard</span>
                </button>
              </div>
              <button className="overlay-primary-button overlay-start-button" onClick={recorder.start}>
                <Mic size={17} />
                <span>Start Recording</span>
              </button>
              <button className="overlay-export-idle-button" onClick={() => window.recall?.showMainWindow?.()} title="Open dashboard to export meetings">
                <Download size={16} />
                <span>Export</span>
              </button>
            </div>
            {error ? <div className="overlay-error overlay-idle-error">{error}</div> : null}
          </>
        ) : isReady ? (
          <>
            <div className="overlay-drag-row">
              <div className="overlay-brand">
                <ReCallLogo className="overlay-mini-logo" />
                <div>
                  <strong>Re: Call</strong>
                  <small>Meeting ready</small>
                </div>
              </div>
            </div>
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
            <OverlayFeed meeting={meeting} recorderStatus={recorder.status} localCards={localOverlayCards} />
          </>
        ) : hasProcessingError ? (
          <>
            <div className="overlay-drag-row">
              <div className="overlay-brand">
                <ReCallLogo className="overlay-mini-logo" />
                <div>
                  <strong>Re: Call</strong>
                  <small>Needs attention</small>
                </div>
              </div>
            </div>
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
            <OverlayFeed meeting={meeting} recorderStatus={recorder.status} localCards={localOverlayCards} />
          </>
        ) : isRecordingOverlay ? (
          <div className="overlay-recording-stage">
            <RecordingInsightGrid meeting={meeting} />
            {[recorder.audioWarning, recorder.systemAudioWarning].filter(Boolean).map((warning) => (
              <div className="overlay-warning overlay-recording-warning" key={warning}>
                {warning}
              </div>
            ))}
            <div className="overlay-recording-bar">
              <div className="overlay-recording-left">
                <ReCallLogo className="overlay-logo" />
                <button className="overlay-dashboard-button" onClick={() => window.recall?.showMainWindow?.()}>
                  <LayoutDashboard size={16} />
                  <span>Dashboard</span>
                </button>
              </div>
              <div className="overlay-recording-center">
                <span className="status-light recording" />
                <strong>{isStopping ? "Saving Audio" : "Recording"}</strong>
                <span>{formatTime(recorder.elapsedSeconds)}</span>
                <div className="mic-meter overlay-recording-meter" title="Microphone input level">
                  <span style={{ transform: `scaleX(${meterLevel})` }} />
                </div>
              </div>
              <button className="overlay-danger-button overlay-stop-button" onClick={recorder.stop} disabled={isStopping}>
                {isStopping ? <LoaderCircle size={16} className="spin" /> : <Square size={16} />}
                <span>{isStopping ? "Stopping" : "Stop"}</span>
              </button>
            </div>
          </div>
        ) : isProcessing || isStarting ? (
          <>
            <div className="overlay-drag-row">
              <div className="overlay-brand">
                <ReCallLogo className="overlay-mini-logo" />
                <div>
                  <strong>Re: Call</strong>
                  <small>{isStarting ? "Starting" : "Transcribing"}</small>
                </div>
              </div>
            </div>
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
            {isProcessing ? <OverlayFeed meeting={meeting} recorderStatus={recorder.status} localCards={localOverlayCards} /> : null}
          </>
        ) : null}
      </section>

      {!isIdle && !isRecordingOverlay ? <footer className="overlay-footer">
        <button onClick={() => window.recall?.showMainWindow?.()}>Dashboard</button>
        <OverlayAskBar onSubmitPrompt={handleOverlayAsk} />
        <span>{activeSessionId ? "Session active" : "Always on top"}</span>
      </footer> : null}
    </main>
  );
}
