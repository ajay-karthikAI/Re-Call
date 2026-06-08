import { Clock3, History } from "lucide-react";

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function MeetingHistory({ meetings, selectedId, onSelect }) {
  return (
    <section className="sidebar-section history-section">
      <div className="sidebar-heading">
        <History size={16} />
        <h2>History</h2>
      </div>
      <div className="history-list">
        {meetings.length ? (
          meetings.map((meeting) => (
            <button
              key={meeting.id}
              className={`history-item ${selectedId === meeting.id ? "selected" : ""}`}
              onClick={() => onSelect(meeting.id)}
            >
              <span className="history-title">{meeting.title}</span>
              <span className="history-meta">
                <Clock3 size={13} />
                {formatDate(meeting.created_at)}
              </span>
              <span className={`mini-status status-${meeting.status}`}>{meeting.status}</span>
            </button>
          ))
        ) : (
          <div className="empty-state compact">No calls yet.</div>
        )}
      </div>
    </section>
  );
}
