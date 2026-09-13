# Problem Statement: Groww Weekly Review Pulse

## Project overview

Build an **AI-agent workflow** for the **Groww** platform (Groww Stocks, Mutual Fund, IPO — Apps on Google Play) that turns **raw mobile-store feedback** into a **weekly pulse** a product team can scan in minutes.

The pulse must answer three questions:

1. **What users care about** (themes)
2. **What they actually said** (verbatim quotes)
3. **What to do next** (action ideas)

Reviews are already public. The job is to **aggregate, theme, summarize, and deliver** that insight through familiar surfaces:

- **Google Docs** for the written pulse
- **Gmail** for a draft the operator can send to themselves

Credentials and REST wiring are **not** handled in application code. Integrations go through **MCP**.

---

## Product under review

| Field | Value |
| --- | --- |
| Product | Groww (Stocks, Mutual Funds, IPO) |
| Store | Google Play |
| Package ID | `com.nextbillion.groww` |
| Locale | `en_IN` |
| Play Store URL | [Groww on Google Play](https://play.google.com/store/apps/details?id=com.nextbillion.groww&hl=en_IN) |

Also pull **recent App Store and Play Store reviews** for the product, within the review-source rules below.

---

## Goal

Turn public app-store reviews into a **one-page weekly health check** that Product, Support, and Leadership can use without reading hundreds of raw reviews.

---

## End-to-end flow (definition of done)

When the workflow is complete, all of the following have happened:

1. **Ingest** — Pull recent App Store and Play Store reviews for Groww (within the rules below).
2. **Theme** — Cluster reviews into a small set of themes and distill a one-page weekly note.
3. **Publish** — Put that note where stakeholders can read it (**Google Docs**).
4. **Notify** — Create a **draft email** to yourself (or an alias) that contains or links to that pulse (**Gmail**).

---

## Deliverables

The **weekly one-page pulse** must include:

| Section | Requirement |
| --- | --- |
| Top themes | What people are talking about most |
| Real user quotes | Verbatim snippets from reviews — **no invented wording** |
| Three action ideas | Concrete next steps grounded in the themes |

**Finally:** send yourself a **draft email** containing this weekly note (or a clear pointer to it).

---

## Who this helps

| Audience | Why it matters |
| --- | --- |
| Product / Growth | Prioritize fixes and improvements from real signals |
| Support | Align messaging with what users are actually saying |
| Leadership | One-page health check without drowning in raw reviews |

---

## What you must build

1. **Import reviews** from roughly the **last 8–12 weeks**. Use fields the export provides, such as:
   - rating
   - title
   - text
   - date
2. **Group reviews into at most 5 themes.** Examples that may fit a brokerage / investing app (pick what the data supports):
   - onboarding
   - KYC
   - payments
   - statements
   - withdrawals
3. **Generate a weekly one-page note** with:
   - **Top 3 themes** (a subset of the clustered themes)
   - **3 user quotes** (verbatim, anonymized)
   - **3 action ideas**
4. **Draft an email** with the note to yourself or an alias.

---

## Pulse content spec

Keep the written note **scannable** and **≤ 250 words** where applicable.

Suggested structure for the Google Doc:

```text
Groww Weekly Review Pulse — [week range]

1. Top 3 themes
   - Theme A — [short why it matters / volume or rating signal]
   - Theme B
   - Theme C

2. What users said (3 quotes)
   - “…” (rating, store, date — no username)

3. Three action ideas
   - Action 1 — tied to theme
   - Action 2
   - Action 3
```

---

## Integrations: Google Docs & Gmail via MCP

Use **MCP (Model Context Protocol)** servers for Google Docs and Gmail, for example:

- creating or updating the pulse document
- creating the draft Gmail message

Do **not** integrate Google APIs directly as the primary path (no bespoke OAuth client + REST client code).

MCP servers expose tools the agent or app can call. Lean on that pattern so Docs and Gmail stay consistent with course tooling and avoid duplicating auth and HTTP plumbing.

**Requirement:** MCP-first. Choose MCP servers or connectors the environment provides for Docs and Gmail. The requirement is not “call Google APIs manually.”

---

## Key constraints

| Area | Rule |
| --- | --- |
| Reviews | Use **public review exports only**. No scraping behind store logins. No ToS-violating automation. |
| Themes | Maximum **5** themes for clustering. The written pulse highlights the **top 3**. |
| Length | Keep the note scannable and **≤ 250 words** where applicable. |
| Privacy | **Do not include PII** — no usernames, emails, device IDs, or other identifiable reviewer data in any artifact. Quotes must be anonymous / stripped as needed. |
| Quotes | Verbatim from reviews only. Do not invent or paraphrase as if it were a quote. |
| Delivery | Pulse lives in **Google Docs**. Operator notification is a **Gmail draft** (not necessarily sent). |
| Auth | No custom credential handling or REST wiring for Google; use MCP. |
| LLM | **Groq Cloud** only (`GROQ_API_KEY`, `langchain-groq`). Do not use the OpenAI API. |

---

## Data rules

**In scope**

- Public App Store / Play Store review exports
- Groww (`com.nextbillion.groww`) reviews from roughly the last 8–12 weeks
- Fields available in the export (rating, title, text, date, store, etc.)

**Out of scope**

- Logged-in scraping or unofficial store APIs that violate ToS
- Reviewer identity, account emails, device IDs, or any PII in outputs
- Direct Google API clients as the main Docs/Gmail integration
- The OpenAI API as the pulse LLM (use Groq)

---

## Success criteria

The project is done when:

- [ ] Reviews covering ~8–12 weeks are imported from public exports
- [ ] Reviews are clustered into **≤ 5** themes
- [ ] A one-page weekly pulse exists with **top 3 themes**, **3 verbatim quotes**, and **3 action ideas**
- [ ] The note is **≤ 250 words**, scannable, and contains **no PII**
- [ ] The pulse is published to **Google Docs via MCP**
- [ ] A **Gmail draft** to self/alias contains the note or a clear link to the Doc (**via MCP**)

---

## Source

This document is the canonical project brief, derived from `Docs/ProblemStatement.txt`.
