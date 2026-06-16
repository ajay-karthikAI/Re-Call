const SUPPORTED_CHART_TYPES = new Set(["line_chart", "bar_chart", "table", "timeline", "needs_data"]);

const GRAPH_CODE_PATTERN =
  /\b(matplotlib|pyplot|seaborn|plotly|recharts|chart\.js|new Chart|plt\.|\.plot\(|\.bar\(|\.pie\(|histogram|line chart|bar chart|graph|chart)\b/i;

export function getStructuredChartCards(notes) {
  const overlayCards = notes?.live_insights?.overlay_cards;
  if (!Array.isArray(overlayCards)) {
    return [];
  }
  return dedupeChartCards(overlayCards.filter((card) => card?.type === "chart"));
}

export function getGraphCodeSnippets(notes) {
  const snippets = Array.isArray(notes?.code_snippets) ? notes.code_snippets : [];
  return snippets.filter(isGraphCodeSnippet);
}

export function getNonGraphCodeSnippets(notes) {
  const snippets = Array.isArray(notes?.code_snippets) ? notes.code_snippets : [];
  return snippets.filter((snippet) => !isGraphCodeSnippet(snippet));
}

export function createMissingGraphCard(message) {
  return {
    type: "chart",
    chart_type: "needs_data",
    title: "Graph data missing",
    missing_data_prompt:
      message ||
      "I found graph code in the final analysis, but no structured chart data was saved for Re: Call to draw.",
    source_type: "final_analysis",
    confidence: "low",
  };
}

export function ChartCard({ card, compact = false }) {
  const chartType = normalizeChartType(card?.chart_type);
  const data = Array.isArray(card?.data) ? card.data : [];
  const detailChips = [
    card?.trigger === "spoken_graph_request" ? "voice graph" : "",
    card?.source_type || "",
    card?.confidence ? `confidence: ${card.confidence}` : "",
    chartType,
  ].filter(Boolean);
  const missingMessage =
    card?.missing_data_prompt || "I heard the graph request, but I need the values before I can draw it.";

  if (chartType === "needs_data") {
    return (
      <div className={`visual-chart-card ${compact ? "visual-chart-card-compact" : ""}`}>
        <p className="chart-missing">{missingMessage}</p>
        <ChartChips chips={detailChips} />
      </div>
    );
  }

  if (!hasRenderableChartData(chartType, data)) {
    return (
      <div className={`visual-chart-card ${compact ? "visual-chart-card-compact" : ""}`}>
        <p className="chart-missing">Graph data missing. Re: Call needs structured labels and values to draw this card.</p>
        <ChartChips chips={detailChips} />
      </div>
    );
  }

  return (
    <div className={`visual-chart-card ${compact ? "visual-chart-card-compact" : ""}`}>
      {chartType === "line_chart" ? (
        <LineChart data={data} />
      ) : chartType === "table" ? (
        <TableChart data={data} />
      ) : chartType === "timeline" ? (
        <TimelineChart data={data} />
      ) : (
        <BarChart data={data} />
      )}
      {card?.insight ? <p className="chart-insight">{card.insight}</p> : null}
      <ChartChips chips={detailChips} />
    </div>
  );
}

export function ChartSection({ title = "Charts", cards = [], compact = false, renderTitle }) {
  if (!cards.length) {
    return null;
  }

  return (
    <div className={`chart-card-list ${compact ? "chart-card-list-compact" : ""}`}>
      {renderTitle ? renderTitle(title) : null}
      {cards.map((card, index) => (
        <article className="chart-card-shell" key={`${card.title || card.chart_type || "chart"}-${index}`}>
          <div className="chart-card-header">
            <span>{card.chart_type === "needs_data" ? "Graph request" : "Visual chart"}</span>
            <strong>{card.title || "Graph request detected"}</strong>
          </div>
          <ChartCard card={card} compact={compact} />
        </article>
      ))}
    </div>
  );
}

function ChartChips({ chips }) {
  if (!chips.length) {
    return null;
  }
  return (
    <div className="chart-card-sources">
      {chips.map((chip) => (
        <span key={chip}>{chip}</span>
      ))}
    </div>
  );
}

function BarChart({ data }) {
  const rows = normalizedChartData(data);
  const max = Math.max(...rows.map((item) => Math.abs(item.value)), 1);
  const ticks = chartTicks(0, max);

  return (
    <div className="chart-bars" role="img" aria-label="Bar chart">
      <div className="chart-axis-labels" aria-hidden="true">
        <span />
        <div>
          {ticks.map((tick) => (
            <span key={tick}>{formatChartValue(tick)}</span>
          ))}
        </div>
        <span />
      </div>
      {rows.map((item) => (
        <div className="chart-bar-row" key={item.label}>
          <span title={item.label}>{item.label}</span>
          <div>
            {ticks.slice(1).map((tick) => (
              <em key={tick} style={{ left: `${Math.min(100, (tick / max) * 100)}%` }} />
            ))}
            <i style={{ width: `${Math.max(7, (Math.abs(item.value) / max) * 100)}%` }} />
            <b>{formatChartValue(item.value, item.rawValue)}</b>
          </div>
          <strong>{formatChartValue(item.value, item.rawValue)}</strong>
        </div>
      ))}
    </div>
  );
}

function LineChart({ data }) {
  const rows = normalizedChartData(data);
  const max = Math.max(...rows.map((item) => item.value), 1);
  const min = Math.min(...rows.map((item) => item.value), 0);
  const range = Math.max(max - min, 1);
  const ticks = chartTicks(min, max);
  const points = rows.map((item, index) => {
    const x = rows.length === 1 ? 150 : 44 + (index / (rows.length - 1)) * 210;
    const y = 86 - ((item.value - min) / range) * 64;
    return { ...item, x, y };
  });
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");

  return (
    <div className="line-chart">
      <svg viewBox="0 0 300 118" role="img" aria-label="Line chart">
        <rect className="line-chart-bg" x="38" y="14" width="224" height="80" rx="6" />
        {ticks.map((tick) => {
          const y = 86 - ((tick - min) / range) * 64;
          return (
            <g key={tick}>
              <line className="line-chart-grid" x1="38" x2="262" y1={y} y2={y} />
              <text className="line-chart-y-label" x="32" y={y + 3}>
                {formatChartValue(tick)}
              </text>
            </g>
          );
        })}
        <path className="line-chart-axis" d="M 38 14 V 94 H 262" />
        {path ? <path className="line-chart-path" d={path} /> : null}
        {points.map((point) => (
          <g key={`${point.label}-${point.x}`}>
            <circle cx={point.x} cy={point.y} r="3.5">
              <title>{`${point.label}: ${formatChartValue(point.value, point.rawValue)}`}</title>
            </circle>
            <text className="line-chart-value-label" x={point.x} y={Math.max(12, point.y - 8)}>
              {formatChartValue(point.value, point.rawValue)}
            </text>
          </g>
        ))}
      </svg>
      <div className="line-chart-labels">
        {points.map((point) => (
          <span key={point.label} title={point.label}>
            {point.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function TableChart({ data }) {
  return (
    <div className="chart-table">
      {(data || []).slice(0, 8).map((item) => (
        <div key={`${item.label}-${item.value || item.text || item.owner || item.severity}`}>
          <span>{item.label}</span>
          <strong>{displayTableValue(item)}</strong>
        </div>
      ))}
    </div>
  );
}

function TimelineChart({ data }) {
  return (
    <div className="chart-timeline">
      {(data || []).slice(0, 8).map((item) => (
        <div key={`${item.label}-${item.text || item.value || item.owner || item.severity}`}>
          <span />
          <p>
            <strong>{item.label}</strong>
            {displayTimelineValue(item) ? <small>{displayTimelineValue(item)}</small> : null}
          </p>
        </div>
      ))}
    </div>
  );
}

function hasRenderableChartData(chartType, data) {
  if (!Array.isArray(data) || data.length === 0) {
    return false;
  }
  if (chartType === "line_chart" || chartType === "bar_chart") {
    return normalizedChartData(data).length > 0;
  }
  return data.some((item) => item && typeof item === "object" && String(item.label || "").trim());
}

function normalizedChartData(data) {
  return (data || [])
    .map((item) => {
      const rawValue = item.value ?? item.severity ?? item.text ?? "";
      return {
        label: String(item.label || "Item"),
        value: chartNumericValue(item),
        rawValue,
      };
    })
    .filter((item) => Number.isFinite(item.value))
    .slice(0, 8);
}

function chartNumericValue(item) {
  if (typeof item.value === "number") {
    return item.value;
  }

  const raw = String(item.value ?? "").trim();
  const parsed = parseHumanNumber(raw);
  if (Number.isFinite(parsed)) {
    return parsed;
  }

  const severity = String(item.severity || item.value || "").toLowerCase();
  if (severity === "high") {
    return 3;
  }
  if (severity === "medium") {
    return 2;
  }
  if (severity === "low") {
    return 1;
  }
  return Number.NaN;
}

function parseHumanNumber(raw) {
  const value = raw.replace(/[$,%]/g, "").replace(/,/g, "").toLowerCase();
  const match = value.match(/^(-?\d+(?:\.\d+)?)(k|m|b)?$/);
  if (!match) {
    return Number.NaN;
  }
  const multiplier = match[2] === "b" ? 1_000_000_000 : match[2] === "m" ? 1_000_000 : match[2] === "k" ? 1_000 : 1;
  return Number(match[1]) * multiplier;
}

function formatChartValue(value, rawValue) {
  if (typeof rawValue === "string" && rawValue.trim()) {
    const parsed = parseHumanNumber(rawValue.trim());
    if (!Number.isFinite(parsed)) {
      return rawValue;
    }
  }
  if (Math.abs(value) >= 1000) {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function chartTicks(min, max) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return [0, 1];
  }
  if (min === max) {
    return [0, max || 1];
  }
  const low = Math.min(min, 0);
  const high = Math.max(max, 1);
  return [low, low + (high - low) / 2, high];
}

function displayTableValue(item) {
  return item.value ?? item.severity ?? item.owner ?? item.text ?? "Included";
}

function displayTimelineValue(item) {
  return item.text ?? item.value ?? item.owner ?? item.severity ?? "";
}

function normalizeChartType(chartType) {
  const value = String(chartType || "needs_data").trim();
  return SUPPORTED_CHART_TYPES.has(value) ? value : "bar_chart";
}

function dedupeChartCards(items = []) {
  const seen = new Set();
  const cards = [];
  items.forEach((item) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const key = String(item.request || item.title || item.chart_type || "").toLowerCase().replace(/\s+/g, " ");
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    cards.push(item);
  });
  return cards;
}

function isGraphCodeSnippet(snippet) {
  if (!snippet || typeof snippet !== "object") {
    return false;
  }
  const text = [snippet.language, snippet.description, snippet.code].filter(Boolean).join("\n");
  return GRAPH_CODE_PATTERN.test(text);
}
