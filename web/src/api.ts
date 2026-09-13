import type { Insights, MailStatus, SubscribeResult } from "./types";

const base = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, init);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = await response.text();
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return response.json() as Promise<T>;
}

export function fetchInsights(weeks: number) {
  return request<Insights>(`/api/insights?weeks=${weeks}`);
}

export function refreshInsights(weeks: number) {
  return request<Insights>(`/api/insights/refresh?weeks=${weeks}`, { method: "POST" });
}

export function fetchMailStatus() {
  return request<MailStatus>("/api/mail/status");
}

export function gmailConnectUrl() {
  return `${base}/api/auth/gmail`;
}

function mailPayload(email: string, includeQuotes: boolean, weeks: number) {
  return {
    method: "POST" as const,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      include_quotes: includeQuotes,
      weeks,
    }),
  };
}

export function subscribe(email: string, includeQuotes: boolean, weeks: number) {
  return request<SubscribeResult>("/api/subscribe", mailPayload(email, includeQuotes, weeks));
}

export function sendNow(email: string, includeQuotes: boolean, weeks: number) {
  return request<SubscribeResult>("/api/mail/send", mailPayload(email, includeQuotes, weeks));
}

export async function downloadReportPdf(weeks: number) {
  const response = await fetch(`${base}/api/export.pdf?weeks=${weeks}`);
  if (!response.ok) {
    throw new Error("Could not export PDF");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  anchor.href = url;
  anchor.download = match?.[1] || `groww-pulse-${weeks}w.pdf`;
  anchor.click();
  URL.revokeObjectURL(url);
}
