import { AlertCircle, CheckCircle2, FileText, LoaderCircle, Plug, RefreshCcw, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

const PROVIDERS = [
  {
    id: "zoom",
    label: "Zoom",
    hint: "Syncs cloud recording audio transcripts after Zoom finishes processing them.",
  },
  {
    id: "teams",
    label: "Teams",
    hint: "Syncs Microsoft Graph transcript files for a Teams meeting join URL.",
  },
  {
    id: "meet",
    label: "Meet",
    hint: "Syncs Google Meet conference transcript entries from your Google account.",
  },
];

export function TranscriptImportPanel({ apiBaseUrl, onImported }) {
  const [provider, setProvider] = useState("zoom");
  const [connections, setConnections] = useState([]);
  const [loadingConnections, setLoadingConnections] = useState(false);
  const [syncingProvider, setSyncingProvider] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [teamsJoinUrl, setTeamsJoinUrl] = useState("");
  const [manualOpen, setManualOpen] = useState(false);

  const [title, setTitle] = useState("");
  const [transcriptText, setTranscriptText] = useState("");
  const [file, setFile] = useState(null);
  const [manualLoading, setManualLoading] = useState(false);

  const selectedProvider = PROVIDERS.find((item) => item.id === provider) || PROVIDERS[0];
  const selectedConnection = useMemo(
    () => connections.find((item) => item.provider === provider),
    [connections, provider]
  );

  const loadConnections = useCallback(async () => {
    setLoadingConnections(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/connections`);
      if (!response.ok) {
        throw new Error("Could not load integrations");
      }
      const data = await response.json();
      setConnections(data.connections || []);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoadingConnections(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    loadConnections();
  }, [loadConnections]);

  function connectSelectedProvider() {
    setError("");
    setMessage(`Finish connecting ${selectedProvider.label} in the browser tab, then click Refresh.`);
    window.open(`${apiBaseUrl}/api/integrations/${provider}/authorize`, "_blank", "noopener,noreferrer");
  }

  async function syncSelectedProvider() {
    setSyncingProvider(provider);
    setError("");
    setMessage("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/integrations/${provider}/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          days: 30,
          limit: 5,
          teams_join_url: provider === "teams" ? teamsJoinUrl.trim() : null,
        }),
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Transcript sync failed");
      }

      const data = await response.json();
      const imported = data.imported_count || 0;
      const skipped = data.skipped_count || 0;
      setMessage(data.detail || `${imported} imported, ${skipped} already in Re: Call.`);
      if (data.meetings?.[0]) {
        onImported?.(data.meetings[0]);
      }
    } catch (syncError) {
      setError(syncError.message);
    } finally {
      setSyncingProvider("");
      loadConnections();
    }
  }

  async function submitManualImport(event) {
    event.preventDefault();
    setManualLoading(true);
    setError("");
    setMessage("");

    try {
      const formData = new FormData();
      formData.append("provider", provider);
      if (title.trim()) {
        formData.append("title", title.trim());
      }
      if (transcriptText.trim()) {
        formData.append("transcript_text", transcriptText.trim());
      }
      if (file) {
        formData.append("transcript_file", file);
      }

      const response = await fetch(`${apiBaseUrl}/api/integrations/transcript`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Transcript import failed");
      }

      const meeting = await response.json();
      setTitle("");
      setTranscriptText("");
      setFile(null);
      event.currentTarget.reset();
      onImported?.(meeting);
    } catch (importError) {
      setError(importError.message);
    } finally {
      setManualLoading(false);
    }
  }

  const configured = selectedConnection?.configured;
  const connected = selectedConnection?.connected;
  const syncing = syncingProvider === provider;

  return (
    <section className="import-panel">
      <div className="import-header">
        <div>
          <FileText size={18} />
          <h2>Transcript Sources</h2>
        </div>
        <button className="mini-refresh" type="button" onClick={loadConnections} disabled={loadingConnections}>
          {loadingConnections ? <LoaderCircle size={13} className="spin" /> : <RefreshCcw size={13} />}
          <span>Refresh</span>
        </button>
      </div>

      <div className="import-form">
        <div className="provider-tabs" role="tablist" aria-label="Transcript provider">
          {PROVIDERS.map((item) => {
            const connection = connections.find((candidate) => candidate.provider === item.id);
            return (
              <button
                type="button"
                key={item.id}
                className={`provider-tab ${provider === item.id ? "selected" : ""}`}
                onClick={() => setProvider(item.id)}
              >
                <span>{item.label}</span>
                {connection?.connected ? <CheckCircle2 size={12} /> : null}
              </button>
            );
          })}
        </div>

        <div className="connection-card">
          <div className="connection-status-row">
            <span className={`connection-dot ${connected ? "connected" : configured ? "ready" : "missing"}`} />
            <strong>{selectedProvider.label}</strong>
            <span>{connected ? "Connected" : configured ? "Ready" : "Needs setup"}</span>
          </div>
          <p>{selectedProvider.hint}</p>
          {selectedConnection?.detail ? <p>{selectedConnection.detail}</p> : null}

          {provider === "teams" ? (
            <label className="import-label compact">
              Teams meeting join URL
              <input
                value={teamsJoinUrl}
                onChange={(event) => setTeamsJoinUrl(event.target.value)}
                placeholder="https://teams.microsoft.com/l/meetup-join/..."
              />
            </label>
          ) : null}

          <div className="connection-actions">
            <button className="connection-button secondary" type="button" onClick={connectSelectedProvider} disabled={!configured}>
              <Plug size={15} />
              <span>{connected ? "Reconnect" : "Connect"}</span>
            </button>
            <button className="connection-button" type="button" onClick={syncSelectedProvider} disabled={!connected || syncing}>
              {syncing ? <LoaderCircle size={15} className="spin" /> : <RefreshCcw size={15} />}
              <span>{syncing ? "Syncing" : "Sync transcripts"}</span>
            </button>
          </div>
        </div>

        {message ? <div className="import-message">{message}</div> : null}
        {error ? (
          <div className="import-error">
            <AlertCircle size={14} />
            <span>{error}</span>
          </div>
        ) : null}

        <button className="manual-toggle" type="button" onClick={() => setManualOpen((current) => !current)}>
          <Upload size={14} />
          <span>{manualOpen ? "Hide manual import" : "Manual fallback import"}</span>
        </button>

        {manualOpen ? (
          <form className="manual-import-form" onSubmit={submitManualImport}>
            <label className="import-label">
              Meeting title
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={`${selectedProvider.label} transcript import`}
              />
            </label>

            <label className="import-dropzone">
              <Upload size={18} />
              <span>{file ? file.name : "Upload .vtt, .srt, .txt, or .docx"}</span>
              <input
                type="file"
                accept=".vtt,.srt,.txt,.docx,text/plain,text/vtt,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(event) => setFile(event.target.files?.[0] || null)}
              />
            </label>

            <label className="import-label">
              Or paste transcript
              <textarea
                value={transcriptText}
                onChange={(event) => setTranscriptText(event.target.value)}
                placeholder="Paste transcript text here..."
                rows={7}
              />
            </label>

            <button className="import-submit" type="submit" disabled={manualLoading || (!file && !transcriptText.trim())}>
              {manualLoading ? <LoaderCircle size={16} className="spin" /> : <Upload size={16} />}
              <span>{manualLoading ? "Importing" : "Import transcript"}</span>
            </button>
          </form>
        ) : null}
      </div>
    </section>
  );
}
