import { useInsights } from "../App";

export default function Pulse() {
  const { data } = useInsights();
  if (!data?.pulse) {
    return (
      <div className="page">
        <h2>Weekly Pulse summary</h2>
        <p className="empty">Pulse is not ready yet.</p>
      </div>
    );
  }
  const pulse = data.pulse;

  async function copyText() {
    const parts = [
      pulse.title,
      "",
      pulse.executive_summary,
      "",
      ...pulse.themes.map(
        (row, index) =>
          `${String(index + 1).padStart(2, "0")} ${row.theme}\n“${row.quote}”`,
      ),
      "",
      "Actions",
      ...pulse.actions.map((row) => `- ${row.title} (${row.owner_hint}): ${row.rationale}`),
    ];
    await navigator.clipboard.writeText(parts.join("\n"));
  }

  return (
    <div className="page">
      <div className="topbar" style={{ marginBottom: "0.8rem" }}>
        <div>
          <h2>Weekly Pulse summary</h2>
          <p className="lede">AI-generated executive summary for {data.iso_week}</p>
        </div>
        <button className="btn" type="button" onClick={() => void copyText()}>
          Copy Text
        </button>
      </div>
      <article className="card pulse-card">
        <div className="pulse-head">
          <h3>Weekly Pulse</h3>
          <div>
            <span className="meta">
              {data.iso_week} / {data.year}
            </span>{" "}
            <span className="conf">Strictly Confidential</span>
          </div>
        </div>
        <p className="meta">EXECUTIVE SUMMARY</p>
        <p>{pulse.executive_summary}</p>
        <p className="meta">TOP THEMES & VERBATIM INSIGHTS</p>
        {pulse.themes.map((row, index) => (
          <div className="theme-block" key={row.theme}>
            <strong>
              <span className="idx">{String(index + 1).padStart(2, "0")}</span>
              {row.theme}{" "}
              <span className={`chip ${row.sentiment === "positive" ? "pos" : row.sentiment === "negative" ? "neg" : "neu"}`}>
                {row.sentiment}
              </span>
            </strong>
            <p className="quote">“{row.quote}”</p>
          </div>
        ))}
        <p className="meta">THREE ACTION IDEAS</p>
        {pulse.actions.map((row) => (
          <p key={row.title}>
            <strong>{row.title}</strong> ({row.owner_hint}) — {row.rationale}
          </p>
        ))}
      </article>
    </div>
  );
}
