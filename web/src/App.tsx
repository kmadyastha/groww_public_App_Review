import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useSearchParams } from "react-router-dom";
import { fetchInsights, refreshInsights, downloadReportPdf } from "./api";
import type { Insights } from "./types";
import Overview from "./pages/Overview";
import Themes from "./pages/Themes";
import Feed from "./pages/Feed";
import Pulse from "./pages/Pulse";
import Subscribe from "./pages/Subscribe";

type Ctx = {
  weeks: number;
  setWeeks: (weeks: number) => void;
  data: Insights | null;
  error: string | null;
  loading: boolean;
  reload: (refresh?: boolean) => void;
};

const InsightsCtx = createContext<Ctx | null>(null);

export function useInsights() {
  const ctx = useContext(InsightsCtx);
  if (!ctx) throw new Error("useInsights outside provider");
  return ctx;
}


export default function App() {
  const [params, setParams] = useSearchParams();
  const weeks = Number(params.get("weeks") || 10);
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  function setWeeks(next: number) {
    const copy = new URLSearchParams(params);
    copy.set("weeks", String(next));
    setParams(copy);
  }

  function reload(refresh = false) {
    setLoading(true);
    setError(null);
    const job = refresh ? refreshInsights(weeks) : fetchInsights(weeks);
    job
      .then((payload) => setData(payload))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    reload(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weeks]);

  const value = useMemo(
    () => ({ weeks, setWeeks, data, error, loading, reload }),
    [weeks, data, error, loading],
  );

  return (
    <InsightsCtx.Provider value={value}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="mark" />
            Groww
          </div>
          <div>
            <div className="nav-label">ANALYTICS</div>
            <nav className="nav">
              <NavLink to={`/?weeks=${weeks}`} end>
                Overview
              </NavLink>
              <NavLink to={`/themes?weeks=${weeks}`}>Theme Clustering</NavLink>
              <NavLink to={`/feed?weeks=${weeks}`}>Review Feed</NavLink>
              <NavLink to={`/pulse?weeks=${weeks}`}>Weekly Pulse</NavLink>
              <NavLink to={`/subscribe?weeks=${weeks}`}>Subscribe</NavLink>
            </nav>
          </div>
          <div className="sidebar-foot">App Review Insights Analyser v2.0</div>
        </aside>
        <section className="main">
          <header className="topbar">
            <h1>App Review Insights Analyser</h1>
            <div className="top-actions">
              <select
                className="weeks"
                value={weeks}
                onChange={(event) => setWeeks(Number(event.target.value))}
              >
                <option value={8}>Last 8 Weeks</option>
                <option value={10}>Last 10 Weeks</option>
                <option value={12}>Last 12 Weeks</option>
              </select>
              <button className="btn" type="button" onClick={() => reload(true)}>
                Refresh
              </button>
              <button
                className="btn btn-mint"
                type="button"
                disabled={!data || exporting}
                onClick={() => {
                  setExporting(true);
                  downloadReportPdf(weeks)
                    .catch((err: Error) => setError(err.message))
                    .finally(() => setExporting(false));
                }}
              >
                {exporting ? "Exporting…" : "Export Report"}
              </button>
            </div>
          </header>
          {loading && (
            <p className="busy">
              Loading insights for the last {weeks} weeks. First run can take a few minutes while
              reviews are classified.
            </p>
          )}
          {error && <p className="msg err">{error}</p>}
          {!loading && !error && (
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/themes" element={<Themes />} />
              <Route path="/feed" element={<Feed />} />
              <Route path="/pulse" element={<Pulse />} />
              <Route path="/subscribe" element={<Subscribe />} />
            </Routes>
          )}
        </section>
      </div>
    </InsightsCtx.Provider>
  );
}
