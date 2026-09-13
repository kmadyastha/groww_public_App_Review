import { useInsights } from "../App";

export default function Overview() {
  const { data } = useInsights();
  if (!data) return null;
  const { overview, window } = data;
  const maxBar = Math.max(...Object.values(overview.rating_distribution), 1);
  const maxTheme = Math.max(...overview.top_themes.map((row) => row.share), 1);
  return (
    <div className="page">
      <h2>Overview</h2>
      <p className="lede">
        Dashboard summary of public Play + App Store reviews ({window.start} to {window.end})
      </p>
      <div className="stats">
        <article className="card">
          <div className="meta">Total Reviews</div>
          <div className="kpi">{overview.total_reviews.toLocaleString()}</div>
        </article>
        <article className="card">
          <div className="meta">Avg Rating</div>
          <div className="kpi">
            {overview.avg_rating.toFixed(1)} <small>★</small>
          </div>
        </article>
        <article className="card">
          <div className="meta">Sentiment Split</div>
          <div className="sent">
            <span title="Positive">
              <span className="emo">😊</span> {overview.sentiment.positive}
            </span>
            <span title="Negative">
              <span className="emo emo-neg">😠</span> {overview.sentiment.negative}
            </span>
            <span title="Neutral">
              <span className="emo emo-neu">😐</span> {overview.sentiment.neutral}
            </span>
          </div>
        </article>
      </div>
      <div className="grid-2">
        <article className="card">
          <h3>Rating Distribution</h3>
          {[5, 4, 3, 2, 1].map((star) => {
            const count = overview.rating_distribution[String(star)] || 0;
            return (
              <div className="bar-row" key={star}>
                <span>{star} ★</span>
                <div className="track">
                  <div className="fill" style={{ width: `${(100 * count) / maxBar}%` }} />
                </div>
                <span>{count}</span>
              </div>
            );
          })}
        </article>
        <article className="card">
          <h3>Top Themes</h3>
          {overview.top_themes.map((row) => (
            <div className="bar-row theme-bar" key={row.name}>
              <span title={row.name}>{row.name}</span>
              <div className="track">
                <div className="fill" style={{ width: `${(100 * row.share) / maxTheme}%` }} />
              </div>
              <span>{Math.round(row.share)}%</span>
            </div>
          ))}
        </article>
      </div>
    </div>
  );
}
