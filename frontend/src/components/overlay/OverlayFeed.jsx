import { Activity, AlertTriangle, BarChart3, FileText, Lightbulb, ListChecks, MessageSquareText, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { ChartCard, getStructuredChartCards } from "../ChartCard.jsx";
import { OverlayCard } from "./OverlayCard.jsx";

function asTextList(items = []) {
  return items
    .map((item) => (typeof item === "string" ? item : item?.text || item?.question || item?.task || ""))
    .map((item) => String(item || "").trim())
    .filter(Boolean);
}

function getInsightState(meeting) {
  const notes = meeting?.notes_json || {};
  const liveTranscript = notes.live_transcript || {};
  const memory = notes.live_memory || {};
  const insights = notes.live_insights || {};
  const overlayCards = Array.isArray(insights.overlay_cards) ? insights.overlay_cards : [];
  const answerCards = overlayCards.filter((card) => card?.type !== "chart");

  return {
    liveTranscript,
    summary: insights.live_summary || memory.summary || "",
    questions: insights.questions?.length ? asTextList(insights.questions) : asTextList(memory.questions),
    suggestedAnswers: dedupeSuggestedAnswers([...answerCards, ...(insights.suggested_answers || [])]),
    chartCards: getStructuredChartCards(notes),
    risks: asTextList(insights.risks),
    actionItems: insights.action_items?.length ? insights.action_items : memory.actions || [],
    error: notes.live_insights_error || "",
  };
}

function getTranscriptPreview(meeting, liveTranscript) {
  const source = liveTranscript.source ? `${liveTranscript.source} audio` : "Microphone audio";
  const status = liveTranscript.status || (meeting?.status === "recording" ? "listening" : meeting?.status || "idle");
  const transcript = liveTranscript.transcript || meeting?.transcript || "";
  const lastLine = transcript
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .at(-1);

  return {
    status,
    source,
    chunkIndex: liveTranscript.chunk_index,
    lastLine,
  };
}

function actionText(item) {
  if (typeof item === "string") {
    return item;
  }
  return [item.owner || "TBD", item.task || item.text || "", item.due || "TBD"].filter(Boolean).join(" - ");
}

function dedupeSuggestedAnswers(items = []) {
  const seen = new Set();
  const answers = [];
  items.forEach((item) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const question = String(item.question || "").trim();
    const answer = String(item.answer || item.text || "").trim();
    const key = question.toLowerCase().replace(/\s+/g, " ");
    if (!question || !answer || seen.has(key)) {
      return;
    }
    seen.add(key);
    answers.push({ ...item, question, answer });
  });
  return answers;
}

export function OverlayFeed({ meeting, recorderStatus = "idle", isRecording = false, localCards = [] }) {
  const [dismissedCards, setDismissedCards] = useState(() => new Set());
  const insights = getInsightState(meeting);

  const cards = useMemo(() => {
    const transcriptStatus = getTranscriptPreview(meeting, insights.liveTranscript);
    const nextCards = [
      {
        id: `transcript-${meeting?.id || "idle"}-${transcriptStatus.chunkIndex || 0}-${transcriptStatus.status}`,
        type: "transcript",
        eyebrow: isRecording ? "Listening" : "Transcript",
        title: isRecording ? "Recording is active" : "Transcript status",
        Icon: Activity,
        tone: isRecording ? "live" : "default",
        body: (
          <div className="overlay-transcript-status">
            <span>{transcriptStatus.status}</span>
            <span>{transcriptStatus.source}</span>
            {typeof transcriptStatus.chunkIndex === "number" ? <span>Chunk {transcriptStatus.chunkIndex + 1}</span> : null}
            {transcriptStatus.lastLine ? <p>{transcriptStatus.lastLine}</p> : null}
          </div>
        ),
      },
    ];

    localCards.forEach((card) => {
      nextCards.push({
        id: card.id,
        type: card.type || "ask_response",
        eyebrow: "Ask Re: Call",
        title: card.prompt || "Local overlay prompt",
        Icon: MessageSquareText,
        tone: "answer",
        body: (
          <div className="overlay-local-answer">
            <p>{card.response || "Ready for backend connection."}</p>
            <div className="overlay-card-sources">
              <span>type: {card.type || "ask_response"}</span>
              <span>source: {card.source_type || "local_overlay"}</span>
              <span>confidence: {card.confidence || "placeholder"}</span>
            </div>
          </div>
        ),
      });
    });

    if (insights.error) {
      nextCards.push({
        id: `error-${meeting?.id || "idle"}`,
        type: "error",
        eyebrow: "Live insight",
        title: "Insight update failed",
        Icon: AlertTriangle,
        tone: "risk",
        body: <p>{insights.error}</p>,
      });
    }

    if (insights.summary) {
      nextCards.push({
        id: `summary-${meeting?.id || "idle"}`,
        type: "summary",
        eyebrow: "Current summary",
        title: "What Re: Call understands",
        Icon: Sparkles,
        tone: "summary",
        body: <p>{insights.summary}</p>,
      });
    }

    insights.chartCards.slice(0, 4).forEach((item, index) => {
      nextCards.push({
        id: `chart-${meeting?.id || "idle"}-${index}-${item.request || item.title}`,
        type: "chart",
        eyebrow: item.chart_type === "needs_data" ? "Graph request" : "Live graph",
        title: item.title || "Graph request detected",
        Icon: BarChart3,
        tone: item.chart_type === "needs_data" ? "risk" : "summary",
        body: <ChartCard card={item} compact />,
      });
    });

    insights.suggestedAnswers.slice(0, 3).forEach((item, index) => {
      const question = item.question || "Suggested answer";
      const answer = item.answer || item.text || "";
      const detailChips = [
        item.trigger === "spoken_question" ? "spoken question" : "",
        item.source_type || "",
        item.confidence ? `confidence: ${item.confidence}` : "",
      ].filter(Boolean);
      nextCards.push({
        id: `answer-${meeting?.id || "idle"}-${index}-${question}`,
        type: "answer",
        eyebrow: item.trigger === "spoken_question" ? "Spoken question" : "Suggested answer",
        title: question,
        Icon: Lightbulb,
        tone: "answer",
        copyText: answer ? `${question}\n\n${answer}` : "",
        body: (
          <>
            {answer ? <p>{answer}</p> : null}
            {item.sources?.length || detailChips.length ? (
              <div className="overlay-card-sources">
                {detailChips.map((chip) => (
                  <span key={chip}>{chip}</span>
                ))}
                {(item.sources || []).map((source) => (
                  <span key={source}>{source}</span>
                ))}
              </div>
            ) : null}
          </>
        ),
      });
    });

    if (insights.risks.length) {
      nextCards.push({
        id: `risks-${meeting?.id || "idle"}-${insights.risks.length}`,
        type: "risks",
        eyebrow: "Risks",
        title: "Watch these points",
        Icon: AlertTriangle,
        tone: "risk",
        body: (
          <ul className="overlay-ai-list">
            {insights.risks.slice(0, 4).map((risk, index) => (
              <li key={`${risk}-${index}`}>{risk}</li>
            ))}
          </ul>
        ),
      });
    }

    if (insights.actionItems.length) {
      nextCards.push({
        id: `actions-${meeting?.id || "idle"}-${insights.actionItems.length}`,
        type: "actions",
        eyebrow: "Action items",
        title: "Next steps detected",
        Icon: ListChecks,
        tone: "default",
        body: (
          <div className="overlay-action-card-list">
            {insights.actionItems.slice(0, 4).map((item, index) => (
              <div key={`${actionText(item)}-${index}`}>
                <span>{typeof item === "string" ? "TBD" : item.owner || "TBD"}</span>
                <strong>{typeof item === "string" ? item : item.task || item.text || "Follow up"}</strong>
                <small>{typeof item === "string" ? "TBD" : item.due || "TBD"}</small>
              </div>
            ))}
          </div>
        ),
      });
    }

    if (insights.questions.length) {
      nextCards.push({
        id: `questions-${meeting?.id || "idle"}-${insights.questions.length}`,
        type: "questions",
        eyebrow: "Questions",
        title: "Open threads",
        Icon: MessageSquareText,
        tone: "default",
        body: (
          <ul className="overlay-ai-list">
            {insights.questions.slice(0, 3).map((question, index) => (
              <li key={`${question}-${index}`}>{question}</li>
            ))}
          </ul>
        ),
      });
    }

    if (nextCards.length === 1 && !meeting) {
      nextCards.push({
        id: "empty",
        type: "empty",
        eyebrow: "Ready",
        title: "Start a meeting to see live cards",
        Icon: FileText,
        tone: "default",
        body: <p>Transcript status, suggested answers, risks, and actions will appear here while Re: Call listens.</p>,
      });
    }

    return nextCards;
  }, [insights, isRecording, localCards, meeting]);

  function dismissCard(cardId) {
    setDismissedCards((current) => {
      const next = new Set(current);
      next.add(cardId);
      return next;
    });
  }

  const visibleCards = cards.filter((card) => !dismissedCards.has(card.id));

  return (
    <section className="overlay-ai-feed" aria-label="Live Re: Call insights">
      <div className="overlay-ai-feed-header">
        <div>
          <Sparkles size={15} />
          <span>Live intelligence</span>
        </div>
        <small>{recorderStatus}</small>
      </div>

      {visibleCards.length ? (
        <div className="overlay-ai-feed-scroll">
          {visibleCards.map((card) => (
            <OverlayCard
              key={card.id}
              id={card.id}
              eyebrow={card.eyebrow}
              title={card.title}
              icon={card.Icon}
              tone={card.tone}
              copyText={card.copyText}
              onDismiss={dismissCard}
            >
              {card.body}
            </OverlayCard>
          ))}
        </div>
      ) : (
        <div className="overlay-ai-empty">All cards dismissed. New live updates will appear as the meeting continues.</div>
      )}
    </section>
  );
}
