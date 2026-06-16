import { Clock3, History, LoaderCircle, Trash2 } from "lucide-react";

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

export function MeetingHistory({ title = "History", meetings, selectedId, onSelect, onDelete, onLoadMore, hasMore = false, loading = false }) {
  return (
    <section className="sidebar-section history-section">
      <div className="sidebar-heading">
        <History size={16} />
        <h2>{title}</h2>
      </div>
      <div className="history-list">
        {meetings.length ? (
          <>
            {meetings.map((meeting) => {
              const deleteDisabled = meeting.status === "recording";
              return (
                <div key={meeting.id} className={`history-item ${selectedId === meeting.id ? "selected" : ""}`}>
                  <button className="history-main-button" onClick={() => onSelect(meeting.id)} title={meeting.title}>
                    <span className="history-title">{meeting.title}</span>
                    <span className="history-meta">
                      <Clock3 size={13} />
                      {formatDate(meeting.created_at)}
                    </span>
                    <span className={`mini-status status-${meeting.status}`}>{meeting.status}</span>
                  </button>
                  <button
                    className="history-delete-button"
                    disabled={deleteDisabled}
                    onClick={() => onDelete?.(meeting)}
                    title={deleteDisabled ? "Stop the active recording before deleting it" : `Delete ${meeting.title}`}
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              );
            })}
            {hasMore ? (
              <button className="history-load-more" onClick={onLoadMore} disabled={loading}>
                {loading ? <LoaderCircle size={14} className="spin" /> : null}
                <span>{loading ? "Loading" : "View More"}</span>
              </button>
            ) : null}
          </>
        ) : (
          <div className="empty-state compact">No calls yet.</div>
        )}
      </div>
    </section>
  );
}
