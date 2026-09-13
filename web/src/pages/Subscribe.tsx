import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchMailStatus, gmailConnectUrl, sendNow, subscribe } from "../api";
import { useInsights } from "../App";
import type { MailStatus } from "../types";

export default function Subscribe() {
  const { data, weeks } = useInsights();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [quotes, setQuotes] = useState(true);
  const [mail, setMail] = useState<MailStatus | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"subscribe" | "send" | null>(null);

  useEffect(() => {
    fetchMailStatus()
      .then(setMail)
      .catch(() => setMail({ connected: false, sender: "", subscribers: 0 }));
  }, [params.get("gmail")]);

  async function onSubscribe(event: FormEvent) {
    event.preventDefault();
    setBusy("subscribe");
    setError(null);
    setStatus(null);
    try {
      const result = await subscribe(email, quotes, weeks);
      setMail((current) =>
        current ? { ...current, subscribers: result.subscribers } : current,
      );
      setStatus(
        `Saved ${result.email} for Monday 09:00 IST.` +
          (result.warning ? ` ${result.warning}` : ""),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Subscribe failed");
    } finally {
      setBusy(null);
    }
  }

  async function onSendNow() {
    const field = document.getElementById("email") as HTMLInputElement | null;
    if (field && !field.reportValidity()) {
      return;
    }
    if (!email.trim()) {
      setError("Enter an email address first");
      return;
    }
    setBusy("send");
    setError(null);
    setStatus(null);
    try {
      const result = await sendNow(email, quotes, weeks);
      setStatus(`Sent this week's pulse to ${result.email} from ${mail?.sender || "Gmail"}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(null);
    }
  }

  const pulse = data?.pulse;
  return (
    <div className="page">
      <h2>Automated Delivery</h2>
      <p className="lede">
        Get the weekly pulse every Monday at 9 AM IST, or send the current note immediately.
      </p>
      <div className="sub-grid">
        <form className="card" onSubmit={(event) => void onSubscribe(event)}>
          <p>
            Subscribe Now adds this address to the Monday 9 AM IST list. Send now emails the current
            pulse immediately. From address is{" "}
            <code>{mail?.sender || "karthik.katu@gmail.com"}</code>.
          </p>
          {!mail?.connected && (
            <p className="warn">
              Gmail OAuth is not connected on the API yet. You can still subscribe; sending starts
              after{" "}
              <a href={gmailConnectUrl()}>Connect Gmail</a>.
            </p>
          )}
          {mail?.connected && (
            <p className="meta">
              Gmail connected · {mail.subscribers} subscriber{mail.subscribers === 1 ? "" : "s"}
            </p>
          )}
          <label className="field" htmlFor="email">
            Email Address
          </label>
          <input
            id="email"
            type="email"
            required
            placeholder="name@company.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label className="check">
            <input
              type="checkbox"
              checked={quotes}
              onChange={(event) => setQuotes(event.target.checked)}
            />
            Include verbatim user quotes in email
          </label>
          <div className="form-actions">
            <button className="btn btn-mint" type="submit" disabled={busy !== null}>
              {busy === "subscribe" ? "Saving…" : "Subscribe Now"}
            </button>
            <button
              className="btn btn-outline"
              type="button"
              disabled={busy !== null}
              onClick={() => void onSendNow()}
            >
              {busy === "send" ? "Sending…" : "Send now"}
            </button>
          </div>
          {status && <p className="msg">{status}</p>}
          {error && <p className="msg err">{error}</p>}
        </form>
        <article className="card">
          <div className="meta">EMAIL PREVIEW</div>
          <h3>
            Weekly Pulse Summary — {data?.iso_week}
          </h3>
          <p className="meta">From: {mail?.sender || "karthik.katu@gmail.com"}</p>
          <p>Hello,</p>
          <p>Here is your weekly summary of app review insights for {data?.iso_week}.</p>
          {pulse?.themes.map((row) => (
            <div
              className={`preview-item ${row.sentiment === "negative" ? "neg" : ""}`}
              key={row.theme}
            >
              <strong>
                {row.theme} ({row.sentiment})
              </strong>
              {quotes && <p>“{row.quote}”</p>}
            </div>
          ))}
        </article>
      </div>
    </div>
  );
}
