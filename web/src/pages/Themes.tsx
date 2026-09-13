import { useInsights } from "../App";

function pct(part: number, total: number) {
  if (!total) return 0;
  return Math.round((100 * part) / total);
}

export default function Themes() {
  const { data } = useInsights();
  if (!data) return null;
  return (
    <div className="page">
      <h2>Theme Clustering</h2>
      <p className="lede">Visual breakdown of review themes and their sentiment distribution</p>
      <div className="theme-grid">
        {data.themes.map((theme) => {
          const total =
            theme.sentiment.positive + theme.sentiment.negative + theme.sentiment.neutral;
          return (
            <article className="card theme-card" key={theme.name}>
              <h3>{theme.name}</h3>
              <div className="meta">
                {theme.share}% of reviews · {theme.count} review{theme.count === 1 ? "" : "s"} ·{" "}
                {theme.avg_rating}★
              </div>
              <div className="sbar">
                <span className="s-pos" style={{ width: `${pct(theme.sentiment.positive, total)}%` }} />
                <span className="s-neg" style={{ width: `${pct(theme.sentiment.negative, total)}%` }} />
                <span className="s-neu" style={{ width: `${pct(theme.sentiment.neutral, total)}%` }} />
              </div>
              <div className="legend">
                <span>
                  <i className="dot s-pos" /> Positive {pct(theme.sentiment.positive, total)}%
                </span>
                <span>
                  <i className="dot s-neg" /> Negative {pct(theme.sentiment.negative, total)}%
                </span>
                <span>
                  <i className="dot s-neu" /> Neutral {pct(theme.sentiment.neutral, total)}%
                </span>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
