import { ArrowRight, ClipboardList, Code2, Lightbulb, ListChecks, Users } from "lucide-react";
import { CodeBlock } from "./CodeBlock.jsx";

export function NotesPanel({ meeting }) {
  const notes = meeting?.notes_json;
  const diagnostics = notes?.capture_diagnostics;
  const hasAnalysis = Boolean(notes?.summary || notes?.participants?.length || notes?.action_items?.length || notes?.error);

  return (
    <section className="pane notes-pane">
      <div className="pane-header">
        <div>
          <ClipboardList size={18} />
          <h2>Notes</h2>
        </div>
        {notes?.sentiment ? <span className="sentiment">{notes.sentiment}</span> : null}
      </div>

      {!hasAnalysis ? (
        <>
          <div className="empty-state">No notes yet.</div>
          {diagnostics ? <CaptureDiagnostics diagnostics={diagnostics} /> : null}
        </>
      ) : notes.error ? (
        <>
          <div className="empty-state error-state">{notes.error}</div>
          {diagnostics ? <CaptureDiagnostics diagnostics={diagnostics} /> : null}
        </>
      ) : (
        <div className="notes-content">
          <section className="note-section">
            <h3>Summary</h3>
            <p>{notes.summary}</p>
          </section>

          {notes.insights?.length ? (
            <section className="note-section">
              <h3>
                <Lightbulb size={16} />
                Insights
              </h3>
              <ul className="clean-list">
                {notes.insights.map((insight) => (
                  <li key={insight}>{insight}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="note-section">
            <h3>
              <Users size={16} />
              Participants
            </h3>
            <div className="tag-row">
              {(notes.participants || []).map((participant) => (
                <span className="tag" key={participant}>
                  {participant}
                </span>
              ))}
            </div>
          </section>

          <section className="note-section">
            <h3>
              <ListChecks size={16} />
              Decisions
            </h3>
            <ul className="clean-list">
              {(notes.key_decisions || []).map((decision) => (
                <li key={decision}>{decision}</li>
              ))}
            </ul>
          </section>

          <section className="note-section">
            <h3>Actions</h3>
            <div className="action-table">
              <div className="action-head">Owner</div>
              <div className="action-head">Task</div>
              <div className="action-head">Due</div>
              {(notes.action_items || []).map((item, index) => (
                <div className="action-row" key={`${item.owner}-${index}`}>
                  <span>{item.owner || "TBD"}</span>
                  <span>{item.task}</span>
                  <span>{item.due || "TBD"}</span>
                </div>
              ))}
            </div>
          </section>

          {notes.next_steps?.length ? (
            <section className="note-section">
              <h3>
                <ArrowRight size={16} />
                Next steps
              </h3>
              <div className="next-step-list">
                {notes.next_steps.map((step, index) => (
                  <div className="next-step" key={`${step.task}-${index}`}>
                    <span>{step.priority || "next"}</span>
                    <strong>{step.task}</strong>
                    {step.reason ? <p>{step.reason}</p> : null}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {notes.code_snippets?.length ? (
            <section className="note-section">
              <h3>
                <Code2 size={16} />
                Code
              </h3>
              {notes.code_snippets.map((snippet, index) => (
                <CodeBlock
                  key={`${snippet.language}-${index}`}
                  language={snippet.language}
                  code={snippet.code}
                />
              ))}
            </section>
          ) : null}

          {diagnostics ? <CaptureDiagnostics diagnostics={diagnostics} /> : null}
        </div>
      )}
    </section>
  );
}

function CaptureDiagnostics({ diagnostics }) {
  const sources = diagnostics.sources || [];

  return (
    <section className="note-section capture-diagnostics">
      <h3>Capture</h3>
      <div className="capture-stat-grid">
        <span>Combined</span>
        <strong>{diagnostics.combined_duration_seconds || 0}s</strong>
        <span>{diagnostics.combined_dbfs == null ? "silent" : `${diagnostics.combined_dbfs} dBFS`}</span>
      </div>
      {sources.map((source) => (
        <div className="capture-stat-grid" key={source.source}>
          <span>{source.source}</span>
          <strong>{source.duration_seconds || 0}s</strong>
          <span>
            {source.chunks || 0} chunks · {source.dbfs == null ? "silent" : `${source.dbfs} dBFS`}
          </span>
        </div>
      ))}
    </section>
  );
}
