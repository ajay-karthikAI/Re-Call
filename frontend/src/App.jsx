import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { CalendarDays, CheckSquare2, Clock3, Home, Users } from "lucide-react";
import { ExportButton } from "./components/ExportButton.jsx";
import { HomeScreen } from "./components/HomeScreen.jsx";
import { LiveInsightsPanel } from "./components/LiveInsightsPanel.jsx";
import { MeetingHistory } from "./components/MeetingHistory.jsx";
import { RecordingBar } from "./components/RecordingBar.jsx";
import { SearchBar } from "./components/SearchBar.jsx";
import { TranscriptImportPanel } from "./components/TranscriptImportPanel.jsx";
import { TranscriptPane } from "./components/TranscriptPane.jsx";
import { useRecorder } from "./hooks/useRecorder.js";
import { useWebSocket } from "./hooks/useWebSocket.js";

const FALLBACK_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const HISTORY_PAGE_SIZE = 30;
const THEME_STORAGE_KEY = "recall-theme";
const DASHBOARD_TABS = [
  { id: "summary", label: "Summary" },
  { id: "transcript", label: "Transcript" },
  { id: "insights", label: "Live Insights" },
];

function apiErrorMessage(error) {
  if (error instanceof TypeError && /fetch/i.test(error.message || "")) {
    return "Backend is starting. Retrying...";
  }
  return error?.message || "Backend is not ready";
}

function formatMeetingDate(value) {
  if (!value) {
    return "No date";
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(totalSeconds = 0) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;

  if (hours) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  }

  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function getSpeakerLabel(meeting) {
  const participants = meeting?.notes_json?.participants || [];
  if (participants.length) {
    return `${participants.length} speaker${participants.length === 1 ? "" : "s"}`;
  }
  return "Speakers pending";
}

function textFromItem(item) {
  if (typeof item === "string") {
    return item;
  }
  return item?.text || item?.question || item?.task || item?.title || "";
}

function textList(items = []) {
  return items.map(textFromItem).map((item) => String(item || "").trim()).filter(Boolean);
}

function getNextSteps(meeting) {
  const notes = meeting?.notes_json || {};
  const liveActions = notes.live_insights?.action_items?.length
    ? notes.live_insights.action_items
    : notes.live_memory?.actions || [];

  const nextSteps = (notes.next_steps || []).map((step) => ({
    priority: typeof step === "string" ? "next" : step.priority || "next",
    task: textFromItem(step) || "Follow up",
    detail: typeof step === "string" ? "" : step.reason || "",
  }));

  const actionItems = (notes.action_items || liveActions || []).map((item) => ({
    priority: typeof item === "string" ? "next" : item.priority || "next",
    task: textFromItem(item) || "Follow up",
    detail: typeof item === "string" ? "" : [item.owner, item.due].filter(Boolean).join(" / "),
  }));

  return [...nextSteps, ...actionItems].filter((step) => step.task).slice(0, 8);
}

function normalizePriority(priority = "") {
  const value = String(priority).toLowerCase();
  if (value.includes("high")) return "high";
  if (value.includes("med")) return "medium";
  if (value.includes("low")) return "low";
  return "next";
}

function getTitleSizeClass(title = "") {
  if (title.length > 96) return "meeting-title-compact";
  if (title.length > 56) return "meeting-title-long";
  return "";
}

function getInitialThemeMode() {
  if (typeof window === "undefined") {
    return "dark";
  }
  const domTheme = document.documentElement.dataset.theme;
  if (domTheme === "light" || domTheme === "dark") {
    return domTheme;
  }

  try {
    const storedTheme = window.localStorage?.getItem(THEME_STORAGE_KEY);
    return storedTheme === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

function storeThemeMode(themeMode) {
  try {
    window.localStorage?.setItem(THEME_STORAGE_KEY, themeMode);
  } catch {
    // Theme persistence is best-effort; the visible theme should still change.
  }
}

export default function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(FALLBACK_API_BASE);
  const [meetings, setMeetings] = useState([]);
  const meetingsRef = useRef([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedMeeting, setSelectedMeeting] = useState(null);
  const [apiError, setApiError] = useState("");
  const [view, setView] = useState("home");
  const [systemAudioStatus, setSystemAudioStatus] = useState({ enabled: false, available: false });
  const [hasMoreMeetings, setHasMoreMeetings] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [activeDashboardTab, setActiveDashboardTab] = useState("summary");
  const [themeMode, setThemeMode] = useState(getInitialThemeMode);
  const lastThemeToggleAtRef = useRef(0);

  useEffect(() => {
    window.recall?.getApiBaseUrl?.().then(setApiBaseUrl).catch(() => setApiBaseUrl(FALLBACK_API_BASE));
    window.recall?.systemAudioStatus?.().then(setSystemAudioStatus).catch(() => setSystemAudioStatus({ enabled: false, available: false }));
  }, []);

  useLayoutEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    document.documentElement.dataset.theme = themeMode;
    storeThemeMode(themeMode);
  }, [themeMode]);

  const toggleThemeMode = useCallback(() => {
    const now = Date.now();
    if (now - lastThemeToggleAtRef.current < 500) {
      return;
    }
    lastThemeToggleAtRef.current = now;

    document.documentElement.classList.add("theme-change-lock");
    window.setTimeout(() => {
      document.documentElement.classList.remove("theme-change-lock");
    }, 180);

    setThemeMode((current) => (current === "light" ? "dark" : "light"));
  }, []);

  const loadMeetings = useCallback(async ({ append = false } = {}) => {
    setHistoryLoading(true);
    try {
      const currentMeetings = meetingsRef.current;
      const offset = append ? currentMeetings.length : 0;
      const requestedLimit = append ? HISTORY_PAGE_SIZE + 1 : Math.max(HISTORY_PAGE_SIZE, currentMeetings.length) + 1;
      const response = await fetch(`${apiBaseUrl}/api/meetings?limit=${requestedLimit}&offset=${offset}`);
      if (!response.ok) {
        throw new Error("Backend is not ready");
      }
      const data = await response.json();
      const pageSize = requestedLimit - 1;
      const page = data.meetings.slice(0, pageSize);
      setHasMoreMeetings(data.meetings.length > pageSize);
      const nextMeetings = append
        ? (() => {
            const seen = new Set(currentMeetings.map((meeting) => meeting.id));
            return [...currentMeetings, ...page.filter((meeting) => !seen.has(meeting.id))];
          })()
        : page;
      meetingsRef.current = nextMeetings;
      setMeetings(nextMeetings);
      setApiError("");
      setSelectedId((current) => {
        if (current && nextMeetings.some((meeting) => meeting.id === current)) {
          return current;
        }
        return nextMeetings[0]?.id || null;
      });
    } catch (error) {
      setApiError(apiErrorMessage(error));
    } finally {
      setHistoryLoading(false);
    }
  }, [apiBaseUrl]);

  const loadMeeting = useCallback(
    async (meetingId) => {
      if (!meetingId) {
        setSelectedMeeting(null);
        return;
      }
      const response = await fetch(`${apiBaseUrl}/api/meetings/${meetingId}`);
      if (response.ok) {
        setSelectedMeeting(await response.json());
      } else if (response.status === 404) {
        setSelectedMeeting(null);
        setSelectedId((current) => (current === meetingId ? null : current));
      }
    },
    [apiBaseUrl]
  );

  useEffect(() => {
    loadMeetings();
    const timer = window.setInterval(loadMeetings, 6000);
    return () => window.clearInterval(timer);
  }, [loadMeetings]);

  useEffect(() => {
    loadMeeting(selectedId).catch(() => {});
  }, [loadMeeting, selectedId]);

  useEffect(() => {
    if (!selectedMeeting || selectedMeeting.status === "complete") {
      return undefined;
    }
    const timer = window.setInterval(() => loadMeeting(selectedMeeting.id), 4000);
    return () => window.clearInterval(timer);
  }, [loadMeeting, selectedMeeting]);

  const handleSessionStarted = useCallback((session) => {
    setView("dashboard");
    setSelectedId(session);
    setSelectedMeeting({
      id: session,
      title: "Live call",
      status: "recording",
      transcript: "",
      notes_json: null,
      duration_seconds: 0,
    });
    loadMeetings();
  }, [loadMeetings]);

  const handleProcessingStarted = useCallback((session) => {
    setSelectedId(session);
    loadMeetings();
    loadMeeting(session);
  }, [loadMeeting, loadMeetings]);

  const handleTranscriptImported = useCallback((meeting) => {
    setView("dashboard");
    setSelectedId(meeting.id);
    setSelectedMeeting(meeting);
    loadMeetings();
    loadMeeting(meeting.id);
  }, [loadMeeting, loadMeetings]);

  const handleDeleteMeeting = useCallback(
    async (meeting) => {
      if (!meeting || meeting.status === "recording") {
        return;
      }

      const confirmed = window.confirm(`Delete "${meeting.title}" from Re: Call history?`);
      if (!confirmed) {
        return;
      }

      try {
        const response = await fetch(`${apiBaseUrl}/api/meetings/${meeting.id}`, { method: "DELETE" });
        if (!response.ok) {
          throw new Error("Could not delete this meeting");
        }

        setMeetings((current) => {
          const next = current.filter((item) => item.id !== meeting.id);
          meetingsRef.current = next;
          if (selectedId === meeting.id) {
            const nextSelectedId = next[0]?.id || null;
            setSelectedId(nextSelectedId);
            if (!nextSelectedId) {
              setSelectedMeeting(null);
            }
          }
          return next;
        });
        setApiError("");
      } catch (error) {
        setApiError(error.message);
      }
    },
    [apiBaseUrl, selectedId]
  );

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

  const recorder = useRecorder({
    apiBaseUrl,
    onSessionStarted: handleSessionStarted,
    onProcessingStarted: handleProcessingStarted,
    startSystemAudioCapture: systemAudioStatus.enabled ? startSystemCapture : undefined,
  });

  const handleSocketMessage = useCallback(
    (message) => {
      if (message?.type === "live_transcript" && message.session_id === selectedId) {
        setSelectedMeeting((current) => {
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

      if (message?.type === "live_insights" && message.session_id === selectedId) {
        setSelectedMeeting((current) => {
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

      if (message?.type === "live_transcript_error" && message.session_id === selectedId) {
        setApiError(message.message || "Live transcript update failed.");
        return;
      }

      if (message?.type === "live_insights_error" && message.session_id === selectedId) {
        setSelectedMeeting((current) => {
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
        return;
      }

      loadMeetings();
      loadMeeting(selectedId);
    },
    [loadMeeting, loadMeetings, selectedId]
  );

  useWebSocket(apiBaseUrl, selectedId, handleSocketMessage);

  async function startFromHome() {
    setView("dashboard");
    await recorder.start();
  }

  if (view === "home") {
    return (
      <HomeScreen
        status={recorder.status}
        error={recorder.error || apiError}
        onStart={startFromHome}
        onDashboard={() => setView("dashboard")}
      />
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-logo-image" src="/recall-logo.png" alt="Re: Call logo" />
          <h1>Re: Call</h1>
        </div>
        <button className="sidebar-home-button" onClick={() => setView("home")}>
          <Home size={26} />
          <span>Home</span>
        </button>
        <SearchBar apiBaseUrl={apiBaseUrl} />
        <TranscriptImportPanel apiBaseUrl={apiBaseUrl} onImported={handleTranscriptImported} />
        <MeetingHistory
          title="Recent Calls"
          meetings={meetings}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onDelete={handleDeleteMeeting}
          onLoadMore={() => loadMeetings({ append: true })}
          hasMore={hasMoreMeetings}
          loading={historyLoading}
        />
        <div className="plan-card">
          <span>You're on</span>
          <strong>Basic Plan</strong>
          <button type="button">Upgrade</button>
        </div>
      </aside>

      <main className="workspace">
        <RecordingBar
          status={recorder.status}
          elapsedSeconds={recorder.elapsedSeconds}
          error={recorder.error || apiError}
          audioLevel={recorder.audioLevel}
          audioWarning={[recorder.audioWarning, recorder.systemAudioWarning].filter(Boolean).join(" ")}
          onStart={recorder.start}
          onStop={recorder.stop}
          onCancel={recorder.cancel}
          activeMeeting={selectedMeeting}
          themeMode={themeMode}
          onToggleTheme={toggleThemeMode}
          exportButton={
            <>
              {window.recall?.showOverlayWindow ? (
                <button className="secondary-button" onClick={() => window.recall.showOverlayWindow()} title="Show desktop overlay">
                  <span>Overlay</span>
                </button>
              ) : null}
              <ExportButton apiBaseUrl={apiBaseUrl} meeting={selectedMeeting} />
            </>
          }
        />

        <section className="dashboard-top">
          <div className="dashboard-title-row">
            <div className="dashboard-title-copy">
              <h1 className={getTitleSizeClass(selectedMeeting?.title || "Call Title")}>
                {selectedMeeting?.title || "Call Title"}
              </h1>
            </div>
          </div>

          <div className="call-meta-grid">
            <div className="call-meta-item">
              <CalendarDays size={16} />
              <span>Date, time</span>
              <strong>{formatMeetingDate(selectedMeeting?.created_at)}</strong>
            </div>
            <div className="call-meta-item">
              <Clock3 size={16} />
              <span>Call length</span>
              <strong>{formatDuration(selectedMeeting?.duration_seconds || recorder.elapsedSeconds)}</strong>
            </div>
            <div className="call-meta-item">
              <Users size={16} />
              <span>Speakers</span>
              <strong>{getSpeakerLabel(selectedMeeting)}</strong>
            </div>
          </div>
        </section>

        <div className="dashboard-body">
          <section className="call-main-panel">
            <div className="call-tabs" role="tablist" aria-label="Call information">
              {DASHBOARD_TABS.map((tab) => (
                <button
                  key={tab.id}
                  className={`call-tab ${activeDashboardTab === tab.id ? "selected" : ""}`}
                  type="button"
                  role="tab"
                  aria-selected={activeDashboardTab === tab.id}
                  onClick={() => setActiveDashboardTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="call-tab-panel" role="tabpanel">
              {activeDashboardTab === "summary" ? (
                <SummaryPane meeting={selectedMeeting} />
              ) : activeDashboardTab === "transcript" ? (
                <TranscriptPane meeting={selectedMeeting} />
              ) : (
                <LiveInsightsPanel meeting={selectedMeeting} />
              )}
            </div>
          </section>

          <NextStepsRail meeting={selectedMeeting} />
        </div>
      </main>
    </div>
  );
}

function SummaryPane({ meeting }) {
  const notes = meeting?.notes_json || {};
  const liveSummary = notes.live_insights?.live_summary || notes.live_memory?.summary || "";
  const summary = notes.summary || liveSummary;
  const insights = textList(notes.insights?.length ? notes.insights : notes.live_insights?.risks || []);
  const decisions = textList(notes.key_decisions || []);
  const participants = notes.participants || [];

  return (
    <section className="pane summary-pane">
      <div className="pane-header">
        <div>
          <CheckSquare2 size={18} />
          <h2>Summary</h2>
        </div>
      </div>
      <div className="notes-content">
        {summary ? (
          <section className="note-section summary-lead">
            <h3>Overview</h3>
            <p>{summary}</p>
          </section>
        ) : (
          <div className="empty-state">No summary yet.</div>
        )}

        {insights.length ? (
          <section className="note-section">
            <h3>Key insights</h3>
            <ul className="clean-list">
              {insights.map((insight, index) => (
                <li key={`${insight}-${index}`}>{insight}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {decisions.length ? (
          <section className="note-section">
            <h3>Decisions</h3>
            <ul className="clean-list">
              {decisions.map((decision, index) => (
                <li key={`${decision}-${index}`}>{decision}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {participants.length ? (
          <section className="note-section">
            <h3>Speakers</h3>
            <div className="tag-row">
              {participants.map((participant) => (
                <span className="tag" key={participant}>
                  {participant}
                </span>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </section>
  );
}

function NextStepsRail({ meeting }) {
  const steps = getNextSteps(meeting);
  const [completedStepsByMeeting, setCompletedStepsByMeeting] = useState({});
  const meetingKey = meeting?.id || "empty";
  const completedSteps = completedStepsByMeeting[meetingKey] || {};

  function toggleStep(stepKey) {
    setCompletedStepsByMeeting((current) => ({
      ...current,
      [meetingKey]: {
        ...(current[meetingKey] || {}),
        [stepKey]: !(current[meetingKey] || {})[stepKey],
      },
    }));
  }

  return (
    <aside className="next-steps-rail">
      <div className="next-steps-heading">
        <CheckSquare2 size={18} />
        <h2>Next Steps</h2>
      </div>

      {steps.length ? (
        <div className="dashboard-next-step-list">
          {steps.map((step, index) => {
            const priority = normalizePriority(step.priority);
            const stepKey = `${step.task}-${index}`;
            const isComplete = Boolean(completedSteps[stepKey]);
            return (
              <div className={`dashboard-next-step ${isComplete ? "is-complete" : ""}`} key={stepKey}>
                <button
                  className="task-checkbox"
                  type="button"
                  aria-label={`${isComplete ? "Unmark" : "Mark"} ${step.task} as complete`}
                  aria-pressed={isComplete}
                  onClick={() => toggleStep(stepKey)}
                />
                <div>
                  <span className={`task-priority priority-${priority}`}>{priority}</span>
                  <strong>{step.task}</strong>
                  {step.detail ? <p>{step.detail}</p> : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="empty-state compact">No next steps yet.</div>
      )}
    </aside>
  );
}
