import { useCallback, useEffect, useRef, useState } from "react";
import { ExportButton } from "./components/ExportButton.jsx";
import { HomeScreen } from "./components/HomeScreen.jsx";
import { LiveInsightsPanel } from "./components/LiveInsightsPanel.jsx";
import { MeetingHistory } from "./components/MeetingHistory.jsx";
import { NotesPanel } from "./components/NotesPanel.jsx";
import { RecordingBar } from "./components/RecordingBar.jsx";
import { SearchBar } from "./components/SearchBar.jsx";
import { TranscriptImportPanel } from "./components/TranscriptImportPanel.jsx";
import { TranscriptPane } from "./components/TranscriptPane.jsx";
import { useRecorder } from "./hooks/useRecorder.js";
import { useWebSocket } from "./hooks/useWebSocket.js";

const FALLBACK_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const HISTORY_PAGE_SIZE = 30;

function apiErrorMessage(error) {
  if (error instanceof TypeError && /fetch/i.test(error.message || "")) {
    return "Backend is starting. Retrying...";
  }
  return error?.message || "Backend is not ready";
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

  useEffect(() => {
    window.recall?.getApiBaseUrl?.().then(setApiBaseUrl).catch(() => setApiBaseUrl(FALLBACK_API_BASE));
    window.recall?.systemAudioStatus?.().then(setSystemAudioStatus).catch(() => setSystemAudioStatus({ enabled: false, available: false }));
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
          <span className="brand-mark">R:</span>
          <div>
            <h1>Re: Call</h1>
            <span>Meeting memory</span>
          </div>
        </div>
        <SearchBar apiBaseUrl={apiBaseUrl} />
        <TranscriptImportPanel apiBaseUrl={apiBaseUrl} onImported={handleTranscriptImported} />
        <MeetingHistory
          meetings={meetings}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onDelete={handleDeleteMeeting}
          onLoadMore={() => loadMeetings({ append: true })}
          hasMore={hasMoreMeetings}
          loading={historyLoading}
        />
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

        <div className="content-grid">
          <TranscriptPane meeting={selectedMeeting} />
          <LiveInsightsPanel meeting={selectedMeeting} />
          <NotesPanel meeting={selectedMeeting} />
        </div>
      </main>
    </div>
  );
}
