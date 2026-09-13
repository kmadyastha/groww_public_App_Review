# Groww Weekly Review Pulse — project briefing

Read this if you need to **explain the project**, **understand MCP before Phase 7**, or **answer interview questions** about it. Canonical product rules stay in `problemStatement.md` and `architecture.md`. This file is the “what is this, and why is it built this way?” layer.

**Status today:** Phases 0–6 are implemented. The agent can ingest public Groww reviews, strip PII, cluster themes, lock verbatim quotes, write a ≤250-word pulse, validate it, and save a **local markdown snapshot**. Google Docs and Gmail are **not** wired yet. That is Phase 7, and it needs MCP servers — not Google API keys in this repo.

---

## 1. The one-sentence pitch

Every week, Product, Support, and Leadership at Groww should get a **one-page health check** of what real users said in the Play Store and App Store — themes, three real quotes, three actions — without reading a thousand reviews, and without this app ever holding Google login secrets.

---

## 2. Layman version (tell this first)

Imagine Groww is a restaurant. Hundreds of people leave reviews on two public noticeboards (Google Play and Apple’s App Store). Nobody on the product team has time to read all of them.

This project is a **weekly briefing writer**:

1. It **collects** the public reviews from the last ~10 weeks (English, long enough to be useful).
2. It **scrubs names, emails, phones, and store IDs** so the briefing cannot dox a reviewer.
3. It **groups** complaints and praise into at most five buckets (charts, charges, order fills, support/KYC, crashes — whatever *this* week’s data actually shows).
4. It **copies three real sentences** from reviews. It is not allowed to “clean up” or invent quotes.
5. It proposes **three concrete next steps** (not slogans like “improve UX”).
6. It writes a **short one-pager** (≤ 250 words) with three headed sections.

**Where you are now (Phase 6):** that one-pager is saved on disk as `data/snapshots/{run_id}.md`. A human can read it and say “yes, this matches the reviews.”

**What is still missing (Phase 7):** put the same one-pager into a **Google Doc** and create a **Gmail draft** to the operator. The app will **not** log into Google itself. It will ask two small helper programs (MCP servers) that already know how to talk to Docs and Gmail.

Think of MCP as **a waiter who does not cook**. Our agent never walks into Google’s kitchen (`docs.googleapis.com`). It hands a ticket to a kitchen station that already has the keys.

---

## 3. What the software actually does

Package name: `pulse`. Entry points: `python -m pulse ingest` (download public reviews) and `python -m pulse.run` (full weekly pipeline).

### 3.1 The pipeline (LangGraph)

A **graph** is a flowchart the computer is forced to follow. That is better here than a free-roaming chatbot, because quotes, PII, theme caps, and “draft not send” are **rules**, not vibes.

```text
LoadReviews
    → SanitizePII          (must happen before any LLM)
    → ClusterThemes        (≤ 5 themes; Groq if key present, else keywords)
    → SelectQuotes         (model may nominate IDs; Python copies substrings)
    → ProposeActions       (3 actions tagged to clustered themes)
    → WritePulse           (≤ 250-word template)
    → ValidatePulse        (fail closed; retry write, never publish junk)
    → PublishDoc           (Phase 6: write snapshot; Phase 7: Docs MCP)
    → DraftEmail           (Phase 6: skip; Phase 7: Gmail draft MCP)
```

Invalid pulses **retry** WritePulse (quote failures retry SelectQuotes first). After a cap of 3 write attempts the run **fails**. MCP / Google is never called on a failed pulse.

### 3.2 Data, not toy labels

Reviews come from **public** sources only:

| Store | How |
| --- | --- |
| Google Play | Public listing (`com.nextbillion.groww`, `en_IN`). No Play Console login. |
| App Store | Official iTunes RSS for app id `1404871703`. Recent-only (~Apple’s public cap), not a full 8–12 week iOS history. |

Quality filter: **≥ 8 English words**. Hinglish / other scripts are dropped.

Themes are **whatever the live export supports** (trading tools, brokerage, execution, support/account access, stability). The problem statement’s old examples (onboarding, statements) are **not forced** if the data does not show them.

Play 1★ volume is allowed to dominate the story. A pile of iOS 5★ “easy to use” reviews must not bury Android trading/support pain.

### 3.3 What is deterministic vs what may use Groq

| Step | Who decides | Why |
| --- | --- | --- |
| Ingest, PII, quote **copy**, word count, validators | Python | Invariants. Never trust a model with “did we leak an email?” |
| Theme labels, quote **nomination**, action wording, prose | Groq (`ChatGroq`) when `GROQ_API_KEY` is set | Analysis can be fuzzy; quotes cannot |
| Without Groq | Keyword clustering + heuristic quotes/actions | Tests and CI must pass **without** a live model |

**LLM is Groq only.** Default model: `qwen/qwen3.6-27b`. No OpenAI, no `api.openai.com`, no `OPENAI_API_KEY`.

Quotes: the model may say “use review id X.” Python then copies an **exact substring** of sanitized `text`. Paraphrase → reject.

### 3.4 Privacy

Before clustering, the sanitizer:

- drops RSS `author` (e.g. `ios.user`)
- redacts emails, phones, UPI, PAN/Aadhaar-like IDs, @handles
- replaces person names with `[user]`
- drops name-like iOS titles (`Pradeep Sholapurkar`) so they cannot become quotes
- hashes store ids → opaque `review_id` (SHA-256 prefix)

Attribution on quotes looks like `(2★, App Store, 2026-07-20)` — never a username.

The validator scans the **final body** again for emails, `ios.user`, iTunes review ids, etc.

### 3.5 Where artifacts live

| Artifact | Location | Google? |
| --- | --- | --- |
| Raw exports | `data/raw/` (gitignored) | No |
| Local pulse (Phase 6) | `data/snapshots/{run_id}.md` | No |
| Google Doc | Phase 7, via Docs MCP | Yes, through MCP |
| Gmail draft | Phase 7, via Gmail MCP | Yes, through MCP — **draft only, never send** |

---

## 4. What MCP is (layman, then precise)

### 4.1 Layman

**MCP = Model Context Protocol.** It is a **shared plug** between an AI program and external tools (files, Slack, Google Docs, Gmail, databases).

Without MCP, every AI app would write its own Google OAuth client, its own Gmail HTTP calls, its own retry logic. That is a lot of secret-handling and a lot of code that is not the product.

With MCP:

- A **server** (small program) knows how to talk to one system (Gmail, Docs, …) and holds the login.
- A **client** (our pulse graph, or Cursor) asks: “what tools do you have?” then calls `create_draft` with JSON arguments.
- The client **never** sees the Google password or OAuth refresh token.

USB-C analogy: one cable shape, many devices. MCP is one conversation shape, many tools.

Restaurant analogy: the pulse agent is the waiter. MCP servers are kitchen stations. Google is the stove. The waiter does not walk into the stove room.

### 4.2 A bit more technical (interview-safe)

MCP is an open protocol (JSON-RPC style) popularized by Anthropic. Typical pieces:

| Piece | In this project |
| --- | --- |
| **Host** | Cursor, a lab runtime, or `python -m pulse.run` |
| **Client** | LangChain `MCPAdapter` / MCP client inside `PublishDoc` and `DraftEmail` |
| **Server** | A Google Docs MCP process and a Gmail MCP process |
| **Transport** | Usually **stdio** (host starts the server as a subprocess) or HTTP/SSE |
| **Tools** | Named functions with JSON schemas: e.g. create document, insert text, create draft |
| **Resources** | Optional readable blobs (we mainly care about **tools**) |
| **Elicitation** | Server can pause and ask the human to re-auth; LangGraph can interrupt and resume |

Auth stays **inside the MCP server** (or the host that launched it). This repo’s `.env` is only `GROQ_API_KEY`. Operator email lives in `config/product.yaml`. **No Google OAuth client, no `googleapis.com` REST, no send-mail tool.**

LangChain’s job is to **turn MCP tools into LangChain tools** so graph nodes can call them. LangGraph’s job is to call those nodes **only after** `ValidatePulse` passes.

### 4.3 How MCP maps onto *this* graph

```text
ValidatePulse  --pass-->  PublishDoc  -->  DraftEmail
                              │                 │
                              ▼                 ▼
                     Docs MCP server      Gmail MCP server
                              │                 │
                              ▼                 ▼
                        Google Doc         Gmail draft
                     (stakeholders)      (operator / alias)
```

| Graph node | MCP intent | Must not do |
| --- | --- | --- |
| `PublishDoc` | Create or update a Doc titled `Groww Weekly Review Pulse — {start} to {end}`; write **only** the validated pulse | Call Google REST; publish an invalid pulse; include raw reviews |
| `DraftEmail` | `drafts.create` to `operator.email`; body = full pulse **or** summary + Doc URL | Bind or call **send** / `messages.send` |

Phase 6 already visits those nodes but **stubs** them: they write a local snapshot (Docs stand-in) and append `PublishDoc skipped: MCP not enabled` / `DraftEmail skipped: MCP not enabled`. Status stays `ready`, not `published`.

Phase 7 **replaces the stubs**, not the analysis. You do **not** re-cluster for Google. You publish the pulse that already passed validation.

---

## 5. Yes: after Phase 6 you need MCP details

You do **not** need MCP to prove the weekly note is good. That was the point of Phase 6 (content freeze).

You **do** need MCP details before writing Phase 7 code, because tool names and how you start the servers are **environment-specific**. The architecture says: use whatever Docs/Gmail MCP servers the runtime provides (Cursor, course lab, local stdio). Do not invent a Google API client “just for now.”

### 5.1 What to gather (checklist for Phase 7)

Fill this in with whoever runs your lab / Cursor MCP config. Until this is known, keep using snapshots.

| Question | Why it matters |
| --- | --- |
| Are **Google Docs** and **Gmail** MCP servers already installed in Cursor / the lab? | If no, Phase 7 stop-if: keep snapshots; do not add REST. |
| How is each server started? (`command` + `args`, or a URL) | Goes in `config/mcp.yaml` — **no secrets**. |
| Exact **tool names** (or at least: create/update Doc, create draft) | We bind by *capability*, but we must not bind send. |
| Where does **Google login** happen? (browser OAuth in the MCP server, Workspace admin, …) | Must not land in this repo’s `.env`. |
| What is the **operator email / alias**? | `config/product.yaml` `operator.email` — draft To: line. |
| Can the Gmail server **send**? | If it offers send, we still **must not bind** it. Draft only. |
| How do we test without Google? | `PULSE_MCP=1` for smoke; CI without the flag still runs allow-list tests. |

You will also want one **human-scanned** snapshot from `data/raw/` (not only the tiny RSS fixture) before calling the analysis “frozen.” That is E6-07 in `Docs/eval.md` (`tests/eval/rubric_phase6.md`).

### 5.2 What you will *not* gather

- A Google Cloud OAuth client ID/secret to paste into this app
- A plan to `pip install google-api-python-client` for Docs/Gmail
- Permission to auto-**send** the weekly email

---

## 6. How to talk about the stack (interview)

**“Is this an agent?”**  
Yes, in the **tool-using workflow** sense: staged graph, structured outputs, external tools. It is **not** an unbounded ReAct loop that can wander into send-mail. Invariants are graph edges and Python validators.

**“Why LangGraph instead of a single prompt?”**  
Because “≤ 5 themes,” “verbatim quotes,” “≤ 250 words,” “no PII,” and “draft not send” are **control-flow** problems. A state machine can retry WritePulse and refuse PublishDoc. A blob of prompt text cannot.

**“Why not OpenAI?”**  
Product constraint: Groq Cloud only. Faster/cheaper inference for this lab shape; keeps secrets to one vendor key.

**“How do you stop the model from inventing quotes?”**  
Split nomination and locking. Model returns review IDs. Python copies a substring. Validator checks every quoted span in the body against sanitized reviews. Paraphrase fails closed.

**“Why MCP instead of Google APIs?”**  
Separation of secrets and plumbing. The pulse repo owns **analysis**. MCP servers own **Google auth and HTTP**. Same pattern as “don’t put the database password in the frontend.” Also matches course/tooling that already speaks MCP.

**“What’s the trust boundary?”**  
This process may hold public reviews and `GROQ_API_KEY`. It must not hold Google tokens. After sanitize, even the LLM only sees hashed ids and redacted text.

**“What if MCP is down?”**  
Phase 6 snapshots still work. Definition of done is incomplete until Docs + draft exist, but you **do not** fall back to a hidden Google client.

**“Idempotency?”**  
Same week window → update the same Doc title in place (Phase 8). Extra Gmail drafts are acceptable (draft-to-self).

**“How do you test without calling Groq or Google?”**  
Fixtures + keyword/heuristic intelligence + mocked writers for retry. Quote tests patch `groq_chat_model`. MCP allow-list tests prove send is unbound. Live Groq/MCP are optional flags, not CI gates for Phases 0–6.

**Current honest status line:**  
“End-to-end **analysis** works locally: public ingest, PII, clustering, locked quotes, validated ≤250-word pulse, snapshot on disk. **Delivery** to Docs/Gmail is designed MCP-first and not implemented until we have server/tool details and a human freeze on a live-export snapshot.”

---

## 7. Glossary

| Term | Meaning here |
| --- | --- |
| **Pulse** | The one-page weekly note (structured `PulseNote` + prose `body`) |
| **LangGraph** | Library for stateful graphs of steps (nodes + edges + retries) |
| **LangChain** | Tool/LLM adapters; Groq chat model; later MCP adapter |
| **Groq** | Hosted LLM API used for clustering/writing — not OpenAI |
| **MCP** | Protocol so the agent can call Docs/Gmail tools without embedding Google SDKs |
| **MCP server** | Process that exposes tools and holds Google credentials |
| **Fail closed** | If a check fails, stop / retry; do not publish a bad pulse |
| **Content freeze** | Human agrees a live-export snapshot is good enough to attach to Google |
| **Draft not send** | Gmail tool creates a draft; sending is out of scope |

---

## 8. Suggested next step (after you review this doc)

1. Scan one snapshot produced from `data/raw/` and fill `tests/eval/rubric_phase6.md`.
2. Write down the MCP checklist in §5.1 (even “we don’t have servers yet” is an answer).
3. Only then implement Phase 7 (`mcp_tools.py`, `config/mcp.yaml`, allow-list tests).

If MCP servers are unavailable, the correct engineering answer is: **keep Phase 6; do not add Google REST.**
