import { useCallback, useEffect, useState } from "react";
import { ExportButton } from "./components/ExportButton.jsx";
import { HomeScreen } from "./components/HomeScreen.jsx";
import { MeetingHistory } from "./components/MeetingHistory.jsx";
import { NotesPanel } from "./components/NotesPanel.jsx";
import { RecordingBar } from "./components/RecordingBar.jsx";
import { SearchBar } from "./components/SearchBar.jsx";
import { TranscriptImportPanel } from "./components/TranscriptImportPanel.jsx";
import { TranscriptPane } from "./components/TranscriptPane.jsx";
import { useRecorder } from "./hooks/useRecorder.js";
import { useWebSocket } from "./hooks/useWebSocket.js";

const FALLBACK_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export default function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(FALLBACK_API_BASE);
  const [meetings, setMeetings] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [selectedMeeting, setSelectedMeeting] = useState(null);
  const [apiError, setApiError] = useState("");
  const [view, setView] = useState("home");

  useEffect(() => {
    window.recall?.getApiBaseUrl?.().then(setApiBaseUrl).catch(() => setApiBaseUrl(FALLBACK_API_BASE));
  }, []);

  const loadMeetings = useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/api/meetings`);
      if (!response.ok) {
        throw new Error("Backend is not ready");
      }
      const data = await response.json();
      setMeetings(data.meetings);
      setApiError("");
      setSelectedId((current) => {
        if (current && data.meetings.some((meeting) => meeting.id === current)) {
          return current;
        }
        return data.meetings[0]?.id || null;
      });
    } catch (error) {
      setApiError(error.message);
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

  const recorder = useRecorder({
    apiBaseUrl,
    onSessionStarted: handleSessionStarted,
    onProcessingStarted: handleProcessingStarted,
  });

  const handleSocketMessage = useCallback(() => {
    loadMeetings();
    loadMeeting(selectedId);
  }, [loadMeeting, loadMeetings, selectedId]);

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
        <MeetingHistory meetings={meetings} selectedId={selectedId} onSelect={setSelectedId} />
      </aside>

      <main className="workspace">
        <RecordingBar
          status={recorder.status}
          elapsedSeconds={recorder.elapsedSeconds}
          error={recorder.error || apiError}
          audioLevel={recorder.audioLevel}
          audioWarning={recorder.audioWarning}
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
          <NotesPanel meeting={selectedMeeting} />
        </div>
      </main>
    </div>
  );
}
