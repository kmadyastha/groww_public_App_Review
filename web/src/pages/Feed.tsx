import { useMemo, useState } from "react";
import { useInsights } from "../App";

function stars(rating: number) {
  return "★".repeat(rating) + "☆".repeat(5 - rating);
}

export default function Feed() {
  const { data } = useInsights();
  const [theme, setTheme] = useState("all");
  const [sentiment, setSentiment] = useState("all");
  const [rating, setRating] = useState("all");
  const [store, setStore] = useState("all");

  const rows = useMemo(() => {
    if (!data) return [];
    return data.reviews.filter((row) => {
      if (theme !== "all" && row.theme !== theme) return false;
      if (sentiment !== "all" && row.sentiment !== sentiment) return false;
      if (rating !== "all" && row.rating !== Number(rating)) return false;
      if (store !== "all" && row.store !== store) return false;
      return true;
    });
  }, [data, theme, sentiment, rating, store]);

  if (!data) return null;
  const themes = data.themes.map((row) => row.name);

  return (
    <div className="page">
      <h2>Review Feed</h2>
      <p className="lede">Recent feedback from public store listings (PII already stripped)</p>
      <div className="filters">
        <select value={theme} onChange={(event) => setTheme(event.target.value)}>
          <option value="all">All Themes</option>
          {themes.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <select value={sentiment} onChange={(event) => setSentiment(event.target.value)}>
          <option value="all">All Sentiments</option>
          <option value="positive">Positive</option>
          <option value="negative">Negative</option>
          <option value="neutral">Neutral</option>
        </select>
        <select value={rating} onChange={(event) => setRating(event.target.value)}>
          <option value="all">All Stars</option>
          {[5, 4, 3, 2, 1].map((star) => (
            <option key={star} value={star}>
              {star} Stars
            </option>
          ))}
        </select>
        <select value={store} onChange={(event) => setStore(event.target.value)}>
          <option value="all">All Stores</option>
          <option value="play">Play Store</option>
          <option value="app_store">App Store</option>
        </select>
        <span className="meta">Showing {rows.length} reviews</span>
      </div>
      {rows.length === 0 && <p className="empty">No reviews match these filters.</p>}
      {rows.slice(0, 80).map((row) => (
        <article className="review" key={row.review_id}>
          <div className="review-top">
            <span>
              <span className="stars">{stars(row.rating)}</span>{" "}
              {row.store === "play" ? "Play" : "iOS"}
            </span>
            <span>{row.date}</span>
          </div>
          <p className="quote">“{row.text}”</p>
          <div className="chips">
            <span className={`chip ${row.sentiment === "positive" ? "pos" : row.sentiment === "negative" ? "neg" : "neu"}`}>
              {row.sentiment}
            </span>
            <span className="chip">{row.theme}</span>
          </div>
        </article>
      ))}
      {rows.length > 80 && <p className="meta">Showing first 80 of {rows.length}. Narrow filters to see more.</p>}
    </div>
  );
}
