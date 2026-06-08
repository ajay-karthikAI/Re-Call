import { FileText } from "lucide-react";

export function TranscriptPane({ meeting }) {
  return (
    <section className="pane transcript-pane">
      <div className="pane-header">
        <div>
          <FileText size={18} />
          <h2>Transcript</h2>
        </div>
        {meeting ? <span className={`mini-status status-${meeting.status}`}>{meeting.status}</span> : null}
      </div>
      <div className="transcript-body">
        {meeting?.transcript ? (
          <p>{meeting.transcript}</p>
        ) : (
          <div className="empty-state">No transcript yet.</div>
        )}
      </div>
    </section>
  );
}
