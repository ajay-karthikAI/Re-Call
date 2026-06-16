import { AlertTriangle, BarChart3, Brain, HelpCircle, Lightbulb, ListChecks } from "lucide-react";
import { ChartSection, getStructuredChartCards } from "./ChartCard.jsx";

function asTextList(items = []) {
  return items
    .map((item) => (typeof item === "string" ? item : item?.text || item?.question || item?.task || ""))
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

function getLiveInsights(meeting) {
  const notes = meeting?.notes_json || {};
  const memory = notes.live_memory || {};
  const insights = notes.live_insights || {};
  const summary = insights.live_summary || memory.summary || "";
  const questions = insights.questions?.length ? asTextList(insights.questions) : asTextList(memory.questions);
  const risks = asTextList(insights.risks);
  const actionItems = insights.action_items?.length ? insights.action_items : memory.actions || [];
  const suggestedAnswers = insights.suggested_answers || [];
  const chartCards = getStructuredChartCards(notes);

  return {
    summary,
    questions,
    risks,
    actionItems,
    suggestedAnswers,
    chartCards,
    error: notes.live_insights_error || "",
    isLive: meeting?.status === "recording",
  };
}

export function LiveInsightsPanel({ meeting, compact = false }) {
  const { summary, questions, risks, actionItems, suggestedAnswers, chartCards, error, isLive } = getLiveInsights(meeting);
  const hasContent = Boolean(
    summary ||
      questions.length ||
      risks.length ||
      actionItems.length ||
      suggestedAnswers.length ||
      chartCards.length ||
      error
  );

  return (
    <section className={`pane live-insights-pane ${compact ? "live-insights-compact" : ""}`}>
      <div className="pane-header">
        <div>
          <Brain size={18} />
          <h2>Live Insights</h2>
        </div>
        {isLive ? <span className="live-pill">Live</span> : null}
      </div>

      <div className="live-insights-content">
        {!hasContent ? (
          <div className="empty-state">Waiting for live insights.</div>
        ) : (
          <>
            {error ? <div className="live-insight-error">{error}</div> : null}

            {summary ? (
              <InsightSection title="Current Summary" icon={Lightbulb}>
                <p>{summary}</p>
              </InsightSection>
            ) : null}

            {chartCards.length ? (
              <InsightSection title="Live Charts" icon={BarChart3}>
                <ChartSection cards={chartCards} compact={compact} />
              </InsightSection>
            ) : null}

            {questions.length ? (
              <InsightSection title="Questions Asked" icon={HelpCircle}>
                <ul className="clean-list">
                  {questions.map((question, index) => (
                    <li key={`${question}-${index}`}>{question}</li>
                  ))}
                </ul>
              </InsightSection>
            ) : null}

            {suggestedAnswers.length ? (
              <InsightSection title="Suggested Answers" icon={Lightbulb}>
                <div className="suggested-answer-list">
                  {suggestedAnswers.map((item, index) => (
                    <div className="suggested-answer" key={`${item.question}-${index}`}>
                      <strong>{item.question}</strong>
                      <p>{item.answer}</p>
                      {item.sources?.length ? (
                        <div className="suggested-answer-sources">
                          {item.sources.map((source) => (
                            <span key={source}>{source}</span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </InsightSection>
            ) : null}

            {risks.length ? (
              <InsightSection title="Risks / Objections" icon={AlertTriangle}>
                <ul className="clean-list">
                  {risks.map((risk, index) => (
                    <li key={`${risk}-${index}`}>{risk}</li>
                  ))}
                </ul>
              </InsightSection>
            ) : null}

            {actionItems.length ? (
              <InsightSection title="Action Items" icon={ListChecks}>
                <div className="live-action-list">
                  {actionItems.map((item, index) => (
                    <div className="live-action-item" key={`${item.task || item.text}-${index}`}>
                      <span>{item.owner || "TBD"}</span>
                      <strong>{item.task || item.text}</strong>
                      <small>{item.due || "TBD"}</small>
                    </div>
                  ))}
                </div>
              </InsightSection>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}

function InsightSection({ title, icon: Icon, children }) {
  return (
    <section className="live-insight-section">
      <h3>
        <Icon size={15} />
        {title}
      </h3>
      {children}
    </section>
  );
}
