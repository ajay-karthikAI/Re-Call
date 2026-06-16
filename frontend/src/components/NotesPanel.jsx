import { ArrowRight, BarChart3, ClipboardList, Code2, Lightbulb, ListChecks, Users } from "lucide-react";
import {
  ChartSection,
  createMissingGraphCard,
  getGraphCodeSnippets,
  getNonGraphCodeSnippets,
  getStructuredChartCards,
} from "./ChartCard.jsx";
import { CodeBlock } from "./CodeBlock.jsx";

export function NotesPanel({ meeting }) {
  const notes = meeting?.notes_json;
  const liveMemory = notes?.live_memory;
  const liveInsights = notes?.live_insights;
  const diagnostics = notes?.capture_diagnostics;
  const chartCards = getStructuredChartCards(notes);
  const graphCodeSnippets = getGraphCodeSnippets(notes);
  const codeSnippets = getNonGraphCodeSnippets(notes);
  const graphFallbackCards = !chartCards.length && graphCodeSnippets.length ? [createMissingGraphCard()] : [];
  const visibleChartCards = chartCards.length ? chartCards : graphFallbackCards;
  const hasAnalysis = Boolean(
    notes?.summary ||
      notes?.participants?.length ||
      notes?.action_items?.length ||
      notes?.error ||
      codeSnippets.length ||
      graphCodeSnippets.length
  );
  const hasLiveMemory = Boolean(
    liveMemory?.summary ||
      liveMemory?.questions?.length ||
      liveMemory?.actions?.length ||
      liveInsights?.live_summary ||
      liveInsights?.questions?.length ||
      liveInsights?.risks?.length ||
      liveInsights?.action_items?.length ||
      liveInsights?.suggested_answers?.length ||
      chartCards.length
  );

  return (
    <section className="pane notes-pane">
      <div className="pane-header">
        <div>
          <ClipboardList size={18} />
          <h2>Notes</h2>
        </div>
        {notes?.sentiment ? <span className="sentiment">{notes.sentiment}</span> : null}
      </div>

      {!hasAnalysis && hasLiveMemory ? (
        <LiveMemoryNotes
          memory={liveMemory || {}}
          insights={liveInsights || {}}
          chartCards={chartCards}
          diagnostics={diagnostics}
        />
      ) : !hasAnalysis ? (
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
          {notes.summary ? (
            <section className="note-section">
              <h3>Summary</h3>
              <p>{notes.summary}</p>
            </section>
          ) : null}

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

          {visibleChartCards.length ? (
            <section className="note-section">
              <h3>
                <BarChart3 size={16} />
                Charts
              </h3>
              <ChartSection cards={visibleChartCards} />
            </section>
          ) : null}

          {notes.participants?.length ? (
            <section className="note-section">
              <h3>
                <Users size={16} />
                Participants
              </h3>
              <div className="tag-row">
                {notes.participants.map((participant) => (
                  <span className="tag" key={participant}>
                    {participant}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          {notes.key_decisions?.length ? (
            <section className="note-section">
              <h3>
                <ListChecks size={16} />
                Decisions
              </h3>
              <ul className="clean-list">
                {notes.key_decisions.map((decision) => (
                  <li key={decision}>{decision}</li>
                ))}
              </ul>
            </section>
          ) : null}

          {notes.action_items?.length ? (
            <section className="note-section">
              <h3>Actions</h3>
              <div className="action-table">
                <div className="action-head">Owner</div>
                <div className="action-head">Task</div>
                <div className="action-head">Due</div>
                {notes.action_items.map((item, index) => (
                  <div className="action-row" key={`${item.owner}-${index}`}>
                    <span>{item.owner || "TBD"}</span>
                    <span>{item.task}</span>
                    <span>{item.due || "TBD"}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

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

          {codeSnippets.length ? (
            <section className="note-section">
              <h3>
                <Code2 size={16} />
                Code
              </h3>
              {codeSnippets.map((snippet, index) => (
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

function LiveMemoryNotes({ memory, insights, chartCards = [], diagnostics }) {
  const actions = insights.action_items?.length ? insights.action_items : memory.actions || [];

  return (
    <div className="notes-content">
      {insights.live_summary || memory.summary ? (
        <section className="note-section">
          <h3>Live summary</h3>
          <p>{insights.live_summary || memory.summary}</p>
        </section>
      ) : null}

      {chartCards.length ? (
        <section className="note-section">
          <h3>Charts</h3>
          <ChartSection cards={chartCards} />
        </section>
      ) : null}

      {(insights.questions?.length || memory.questions?.length) ? (
        <section className="note-section">
          <h3>Questions</h3>
          <ul className="clean-list">
            {(insights.questions?.length ? insights.questions : memory.questions || []).map((question, index) => (
              <li key={`${typeof question === "string" ? question : question.start}-${index}`}>
                {typeof question === "string" ? question : question.text}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {insights.risks?.length ? (
        <section className="note-section">
          <h3>Risks</h3>
          <ul className="clean-list">
            {insights.risks.map((risk, index) => (
              <li key={`${risk}-${index}`}>{risk}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {actions.length ? (
        <section className="note-section">
          <h3>Actions</h3>
          <div className="action-table">
            <div className="action-head">Owner</div>
            <div className="action-head">Task</div>
            <div className="action-head">Due</div>
            {actions.map((item, index) => (
              <div className="action-row" key={`${item.start}-${index}`}>
                <span>{item.owner || "TBD"}</span>
                <span>{item.task || item.text}</span>
                <span>{item.due || "TBD"}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {insights.suggested_answers?.length ? (
        <section className="note-section">
          <h3>Suggested answers</h3>
          <div className="next-step-list">
            {insights.suggested_answers.map((item, index) => (
              <div className="next-step" key={`${item.question}-${index}`}>
                <strong>{item.question}</strong>
                <p>{item.answer}</p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {diagnostics ? <CaptureDiagnostics diagnostics={diagnostics} /> : null}
    </div>
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
