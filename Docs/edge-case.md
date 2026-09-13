# Edge Cases: Groww Weekly Review Pulse

Catalog of corner scenarios for the LangGraph pipeline in `Docs/architecture.md`, aligned with phase gates in `Docs/implementation-plan.md`.

**Default policy:** fail closed on data, privacy, quote fidelity, and shape. Retry only `WritePulse` (and quote nomination) with a cap. Never invent reviews or quotes. Never publish or draft an invalid pulse. Never bind Gmail **send**.

Legend for **Handling**:

| Handling | Meaning |
| --- | --- |
| **Fail closed** | Stop the run; `status=failed`; no Doc, no Gmail draft |
| **Retry** | Re-run the named node up to N times, then fail closed |
| **Drop row** | Exclude that review; continue if enough remain |
| **Degrade** | Complete the run; record a warning in `errors[]` / logs |
| **Reject config** | Do not start the graph |
| **Interrupt** | Pause for operator (MCP elicitation); resume or fail |

---

## 1. Configuration and schema (Phase 0)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| CFG-01 | `product.yaml` missing or invalid YAML | Reject config | Do not start with defaults that invent a product |
| CFG-02 | `product.play_id` not `com.nextbillion.groww` | Reject config or require explicit override | Wrong-app reviews are a silent product failure |
| CFG-03 | `window.weeks` &lt; 8 or &gt; 12 | Reject config | Problem statement is 8–12 only |
| CFG-04 | `limits.max_themes` ≠ 5, `pulse_themes` ≠ 3, `quotes` ≠ 3, `actions` ≠ 3, `max_words` ≠ 250 | Reject config | Invariants are not tunable at runtime |
| CFG-05 | `product.app_store_id` still a placeholder at ingest | Fail closed at `LoadReviews` for App Store; Play may still load | Do not guess an iOS ID |
| CFG-06 | `operator.email` empty when MCP is enabled | Fail closed at `DraftEmail` (Doc may already exist) | Phase 8: report both statuses |
| CFG-07 | `GROQ_API_KEY` missing when intelligence nodes run | Fail closed at first Groq node | Phase 6 snapshot must not be fake |
| CFG-11 | `llm.model` is an OpenAI/Anthropic id (`openai:gpt-4o-mini`, …) | Reject config | Groq catalog ids only |
| CFG-08 | `PulseNote` constructed with 4 quotes / 2 actions | Schema or validator reject | Implementation-plan Phase 0/5 |
| CFG-09 | Env overrides conflict with YAML (e.g. weeks=4) | Same as CFG-03 | Env is not a backdoor past invariants |
| CFG-10 | `.env` contains Google OAuth tokens | Out of scope; do not read them | MCP servers hold Google creds |

---

## 2. Ingest — files, identity, window (Phase 1)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| ING-01 | No Play file and App Store RSS empty | Fail closed | Do not invent reviews |
| ING-02 | Export exists but **all** rows outside the 8–12 week window (stale) | Fail closed | Architecture §13 “empty or stale export” |
| ING-03 | File empty / zero bytes / header-only CSV | Fail closed | |
| ING-04 | Malformed CSV (unbalanced quotes, wrong delimiter) | Fail closed with parse error | Do not silently skip the whole file as “zero reviews” without saying why |
| ING-05 | JSON that is a dict instead of a list (or unknown schema) | Fail closed | |
| ING-06 | Encoding: UTF-8 BOM, UTF-16, mixed Hindi/English | Decode as UTF-8 (BOM-safe); fail if undecodable | Keep Devanagari; do not drop non-ASCII |
| ING-07 | Missing required column (`text`/`body`, `date`, `rating`) | Fail closed or map documented aliases; if unmapped, fail | Do not pad with empty text |
| ING-08 | Extra columns: author, email, device, IP | **Drop columns at parse**; do not map onto `RawReview` | Privacy starts at ingest |
| ING-09 | Rows for a different package ID mixed into the export | Drop those rows | Keep only Groww |
| ING-10 | Locale ≠ `en_IN` when `play_hl` is `en_IN` | Drop or keep only matching locale | Do not mix unrelated locales into the pulse |
| ING-11 | Review **on** window start or end date | **Include** (inclusive window) | Boundary must be tested |
| ING-12 | Datetime with timezone vs date-only | Normalize to calendar date in `en_IN` (IST) before compare | Avoid excluding “today” due to UTC |
| ING-13 | Future-dated reviews | Drop row | Treat as bad data |
| ING-14 | Duplicate `review_id_source` within one store | Keep one (first or latest by date) | Deterministic |
| ING-15 | Same user text on Play **and** App Store | Keep both; different `store` + hash | Not a duplicate |
| ING-16 | Rating missing, 0, 6, 4.5, or `"five"` | Drop if not integer 1–5; do not coerce creatively | |
| ING-17 | Empty `text` **and** empty `title` | Drop row | Loader rule: drop empty text |
| ING-18 | Empty `text` but non-empty `title` | Treat title as body **or** drop — pick one and test it | Recommend: use title if text empty, then still drop if whitespace-only |
| ING-19 | Whitespace-only / `"..."` / emoji-only body | Drop if no alphanumeric content after strip | Avoid quote-locking on `"🔥"` |
| ING-20 | Extremely long review (e.g. 10k+ chars) | Keep; truncate only for LLM context, never for stored quote source | Quote copy must still be a real substring of full sanitized text |
| ING-21 | HTML, markdown, `&amp;`, `<br>` | Strip tags to plain text **before** sanitize | Quotes should not contain raw HTML |
| ING-22 | Play only, App Store unavailable | Continue with Play if count &gt; 0; warn | Partial store coverage is allowed |
| ING-23 | App Store only | Same as ING-22 | |
| ING-24 | App Store RSS returns only ~50 most recent, not 8–12 weeks | Use what the public feed gives; document gap; do not scrape login | Prefer saved public export if RSS is too short |
| ING-25 | RSS/network timeout | Fail App Store adapter; apply ING-22 | No retry loop that looks like aggressive scraping |
| ING-26 | Operator requests Play Console / logged-in scrape | **Do not implement** | Implementation-plan Phase 1 stop-if |
| ING-27 | Wrong file dropped (`com.other.app` CSV) | Zero Groww rows → fail closed | Same as empty after filter |

---

## 3. Volume and mix after load

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| VOL-01 | 0 reviews after filters | Fail closed | No pulse |
| VOL-02 | 1–2 reviews | Fail closed **or** fail at `SelectQuotes` (cannot supply 3 verbatim quotes from distinct enough text) | Prefer fail closed: 3 quotes are mandatory |
| VOL-03 | Exactly 3 reviews | Proceed; all three become quote sources if they pass sanitize | Fragile but valid |
| VOL-04 | Thousands of reviews | Batch in `ClusterThemes`; full set still sanitized | Architecture §7.3 |
| VOL-05 | All 5★ praise | Still cluster and pulse; actions may be “protect what’s working” but must stay concrete | Do not skip negative-weight ranking |
| VOL-06 | All 1★ | Same pipeline; ranking will surface severity | |
| VOL-07 | One theme is ~90% of volume | Top 3 still required; include smaller high-severity themes via negative-rating weight | Architecture ranking rule |
| VOL-08 | Play and App Store disagree (e.g. iOS KYC vs Android payments) | Separate `store` on quotes; themes may span both | Pulse should not pretend one store is the other |

---

## 4. Privacy and sanitization (Phase 2)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| PII-01 | Email in body (`user@gmail.com`) | Redact before LLM | |
| PII-02 | Indian mobile: `9876543210`, `+91 98765 43210`, `09876543210` | Redact | |
| PII-03 | International `+1-555-0100` style | Redact | |
| PII-04 | Author/username column still in file | Already dropped at ingest; if present in body (`- @handle`) | Redact handles |
| PII-05 | Device / GAID / IDFA / Android ID-like tokens | Redact | |
| PII-06 | Person name in body (“Call Ramesh in support”) | Conservative replace with `[user]` | Over-redaction preferred to leaks |
| PII-07 | UPI VPA (`name@oksbi`, `name@upi`) | Redact | Identifiable payment handle |
| PII-08 | PAN / Aadhaar-like patterns | Redact | Even if rare in store reviews |
| PII-09 | Account/client ID, order ID, folio number | Redact long numeric IDs | Safer for a brokerage app |
| PII-10 | After redaction, body is empty | Drop row | May trigger VOL-01 / SAN-empty |
| PII-11 | **All** reviews empty after sanitize | Fail closed | Architecture §13 |
| PII-12 | PII only in `title` | Redact title too | Quotes may come from title |
| PII-13 | LLM re-inserts an email into the pulse | `ValidatePulse` PII regex fail → retry write | Second line of defense |
| PII-14 | Logs print raw author or email | Forbidden | Log `review_id` hashes only |
| PII-15 | `data/raw/` committed to git | `.gitignore` must prevent; Phase 8 review | |
| PII-16 | Snapshot / Doc / draft contains username | Validator fail; do not publish | |
| PII-17 | `review_id` equals store source id | Forbidden | Must be opaque hash |
| PII-18 | Quote attribution includes author | Forbidden | Format: `(4★, Play Store, 2026-08-12)` |
| PII-19 | False positive: “KYC” or “Groww” treated as a person name | Do not redact product/theme terms | Tune NER/allow-list |
| PII-20 | Sanitizer runs **after** an LLM call | Forbidden | Graph order is ingest → sanitize → cluster |

---

## 5. Theme clustering (Phase 4a)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| THM-01 | Model returns 6+ themes | Reject/retry or fold into 5; **never** pass 6+ downstream | Architecture §7.3 / §13 |
| THM-02 | Model returns 0 themes | Retry cluster; then fail closed | Cannot write top 3 |
| THM-03 | Model returns 1–2 themes | Allowed for clusters if data truly has &lt; 3; **pulse still needs 3 theme bullets** | If fewer than 3 clusters exist, fail closed or split largest cluster — **do not invent a theme with zero reviews** |
| THM-04 | Duplicate theme names (`Payments` / `payments` / `Payment`) | Merge case-insensitively | |
| THM-05 | Writer invents a 6th theme in prose | `ValidatePulse` fail (names ⊆ clustered set; exactly 3 in the note) | |
| THM-06 | Seed labels (onboarding, KYC, …) do not fit (e.g. “app crash”) | Data may replace seeds; still cap at 5 | Architecture allows replace |
| THM-07 | Unassigned reviews (no theme) | Force into an `Other` **only if** that keeps total ≤ 5; else redistribute | `Other` must not become a 6th |
| THM-08 | Batch map-reduce produces inconsistent labels across chunks | Reduce step must canonicalize to ≤ 5 keys | VOL-04 |
| THM-09 | Ranking by volume only hides a small but 1★ KYC outage | Rank `(volume, negative-rating weight)` | Architecture §7.3.3 |
| THM-10 | Top 3 omits a clustered theme that had the chosen quote | Quotes should prefer top 3 themes; if a quote’s theme is #4–5, re-pick or swap | Keep pulse coherent |
| THM-11 | Structured output JSON invalid | Retry cluster; then fail closed | Do not regex-parse a 6th theme out of prose |

---

## 6. Quotes (Phase 4b) — highest integrity risk

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| QTE-01 | Model paraphrases or invents wording | Reject; Python copies substring only; retry nomination | Architecture §7.4 |
| QTE-02 | Model returns text that is not a substring (extra adjective, ellipsis, typo-fix) | Reject | Even “helpful” edits are invalid |
| QTE-03 | Same `review_id` nominated three times | Reject; require 3 distinct `review_id`s | |
| QTE-04 | Nominated id not in `state.reviews` | Reject | Hallucinated id |
| QTE-05 | Quote from **pre-sanitize** text (email still visible) | Forbidden | Substring check is against `SanitizedReview` |
| QTE-06 | Unicode normalization: NFC vs NFD, smart quotes, NBSP | Normalize both sides the same way **before** substring test | Avoid false reject/false accept |
| QTE-07 | Quote is entire 10k-char review | Allow a **contiguous substring** copy; writer may shorten only by choosing a shorter exact slice, not by rewriting | Still verbatim |
| QTE-08 | Very short quote (`"bad"`, `"scam"`) | Prefer longer slices; reject if below a minimum length (e.g. 20 chars) **unless** that is the whole review | Still must be substring |
| QTE-09 | All remaining reviews too short or emoji-only | Fail closed | Cannot meet 3 quotes |
| QTE-10 | Title nominated vs body | Copy from `title` or `text`; both must be sanitized | ING-18 |
| QTE-11 | Writer restates the quote in the Doc with different words | Validator: each of the 3 quoted strings in the **body** must match locked `Quote.text` | Dual check: SelectQuotes + ValidatePulse |
| QTE-12 | Ellipsis added: `"KYC stuck…"` when original has no ellipsis | Reject | Invented characters |
| QTE-13 | Translation of a Hindi review into English presented as a quote | Reject | Quotes must be verbatim source language |
| QTE-14 | Attribution missing store/date/rating or includes a name | Validator fail | |
| QTE-15 | Fewer than 3 reviews pass QTE-08 | Fail closed | Do not duplicate quotes to fill the slot |

---

## 7. Actions (Phase 4c)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| ACT-01 | Slogan only (“Improve UX”) | Retry actions; validator may require a verb + surface (screen/flow) | Architecture §7.5 |
| ACT-02 | Action tagged to a theme **not** in `clusters` | Reject / retry | |
| ACT-03 | All 3 actions on one theme, ignoring the other top themes | Degrade warning **or** retry with “one action per top theme” preference | Prefer coverage of top 3 |
| ACT-04 | Duplicate / near-duplicate actions | Retry | |
| ACT-05 | `owner_hint` not in Product / Support / Growth | Coerce to nearest or retry | |
| ACT-06 | Action implies accessing non-public data or scraping | Reject content; keep public-review scope | |
| ACT-07 | Writer drops an action in prose (only 2 listed) | `ValidatePulse` shape fail → retry write | Structured `PulseNote` still has 3 |

---

## 8. Pulse writing and length (Phase 4d–5)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| WRT-01 | Body 251 words | Retry `WritePulse` with count in feedback | Architecture §13 |
| WRT-02 | Body exactly 250 words | Pass | Inclusive limit |
| WRT-03 | Word count disagrees: markdown `**bold**`, hyphenation, numbers, URLs | Define tokenizer (Unicode split on whitespace) and test it | Same function in writer feedback and validator |
| WRT-04 | Missing section (no quotes heading) | Retry write | Template is mandatory |
| WRT-05 | Non-scannable wall of text (one paragraph, 249 words) | Retry if structure regex fails (must have 3 numbered/headed sections) | Problem statement: scannable |
| WRT-06 | Window dates in title disagree with `state.window` | Retry / overwrite title from state | `Groww Weekly Review Pulse — {start} to {end}` |
| WRT-07 | Product name not Groww | Retry | |
| WRT-08 | Retry N exhausted | Fail closed; **do not** `PublishDoc` | Implementation-plan Phase 5 |
| WRT-09 | Valid structured `PulseNote` but prose contradicts it (4th theme, extra quote) | Validator fail | Prose is what stakeholders read |
| WRT-10 | Language mix unexplained (Hindi quotes, English analysis) | Allowed if quotes stay verbatim; analysis in English is fine | QTE-13 still applies |

---

## 9. Graph control flow (Phases 3, 5)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| GRF-01 | Empty sanitized set continues to cluster | Forbidden | Phase 3 exit criterion |
| GRF-02 | `ValidatePulse` fail then MCP still called | Forbidden | |
| GRF-03 | Infinite retry (N not capped) | Forbidden | Cap N, then fail |
| GRF-04 | Two weekly runs at once (overlapping `run_id`) | Independent `run_id`s; Doc idempotency by **title/window**, not by run | Phase 8 |
| GRF-05 | Crash mid-graph after Doc create, before draft | Status shows Doc URL if known; `email` null; `failed` or `partial` | Do not roll back the Doc |
| GRF-06 | Downstream node re-fetches raw reviews | Forbidden | State is the source after load |
| GRF-07 | Stub MCP nodes in Phase 6 still “publish” | Must record skipped; `status=ready` not `published` | Content-freeze gate |

---

## 10. MCP — Docs and Gmail (Phases 7–8)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| MCP-01 | Docs and Gmail MCP servers not configured | Keep Phase 6 snapshots; **do not** add Google REST | Implementation-plan Phase 7 stop-if |
| MCP-02 | MCP offers `send_email` / `messages.send` | **Do not bind** | Allow-list only draft + docs |
| MCP-03 | Agent calls send despite allow-list | Treat as product bug; tests must prove send is unbound | |
| MCP-04 | Auth elicitation / expired Google token | LangGraph **interrupt**; operator resumes; or fail closed | Architecture §8.3 |
| MCP-05 | Docs succeeds, Gmail tool missing / fails | Fail `DraftEmail`; **keep Doc**; report both statuses | Architecture §13 |
| MCP-06 | Docs fails, Gmail would succeed | Do not draft a “success” email without a Doc unless body contains full pulse only — prefer fail before draft | Sequence is PublishDoc → DraftEmail |
| MCP-07 | Rerun same window creates a second Doc | Update in place by title | Idempotency |
| MCP-08 | Rerun creates a second Gmail draft | Allowed (draft-to-self) | Architecture §13 |
| MCP-09 | Tool names differ (`create_document` vs `docs.create`) | Bind by capability, not a hardcoded vendor name | Architecture §8.2 |
| MCP-10 | Tool result has no URL / document id | Fail `PublishDoc` (cannot notify with a pointer) | Unless draft includes **full** pulse text |
| MCP-11 | Draft To: wrong person (empty, group, public) | Only `operator.email` / alias from config | |
| MCP-12 | Draft body empty | Fail `DraftEmail` | Must contain note **or** clear Doc link |
| MCP-13 | Pulse in Doc has PII that validator missed | Do not rely on Google; fix validator; consider Doc update to redact | Defense in depth |
| MCP-14 | Stdio MCP process crash / timeout | Fail that node; no REST fallback | |
| MCP-15 | Operator pastes Google API client “just for now” | Out of scope; reject in review | Architecture §16 |
| MCP-16 | `PULSE_MCP` unset in CI | Skip live MCP tests; allow-list unit tests still run | Implementation-plan Phase 7 |

---

## 11. LLM and runtime (Groq)

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| LLM-01 | Groq rate limit / 429 (TPM/RPM) | Bounded retry with backoff on that node; then fail closed | Chunk clustering; do not skip validation |
| LLM-02 | Truncated JSON (max tokens) | Retry with smaller batch or lower max reviews in prompt | Groq max completion varies by catalog id |
| LLM-03 | Model refuses (safety) on angry reviews | Retry with “public store review analysis” framing; if still blocked, fail closed | Do not invent a calm fake pulse |
| LLM-04 | Model ignores structured schema | Schema validation fail → retry; tests use mocks | Do not trust the model; do not switch to OpenAI |
| LLM-05 | Prompt accidentally includes `RawReview` author fields | Cannot happen if only `SanitizedReview[]` is passed | Type the node inputs |
| LLM-06 | `OPENAI_API_KEY` present or code imports `openai` for chat | Out of scope; reject in review | Pulse LLM is Groq (`src/pulse/llm.py`) |

---

## 12. Product / Groww-specific content

| ID | Scenario | Expected handling | Notes |
| --- | --- | --- | --- |
| PRD-01 | Reviews about a different Groww surface (e.g. Credit) mixed in the same listing | Cluster as data dictates; do not drop unless package ID differs | Same app id |
| PRD-02 | Regulatory / “SEBI / scam / freeze” language | Keep verbatim in quotes; actions stay operational, not legal advice | Still public reviews |
| PRD-03 | Review is only a star rating with no words | Already dropped at ingest | ING-17 |
| PRD-04 | Spam / bot repeats the same sentence 40 times | Dedupe by normalized text **within store** optional; do not let one paste dominate volume ranking | Degrade/dedupe, do not fail |
| PRD-05 | Off-topic review (e.g. delivery food) | May land in a small theme; cap still 5 | Do not invent Groww meaning |

---

## 13. Failure × artifact matrix

What exists after the run for common failures:

| Failure | Snapshot (Phase 6) | Google Doc | Gmail draft | `status` |
| --- | --- | --- | --- | --- |
| Empty/stale ingest | No | No | No | `failed` |
| All PII-stripped empty | No | No | No | `failed` |
| Cannot lock 3 quotes | No | No | No | `failed` |
| Write/validate retries exhausted | No valid pulse | No | No | `failed` |
| Content OK, MCP off | Yes | No | No | `ready` |
| Content OK, Docs OK, Gmail fail | Yes | Yes | No | `failed` (partial report) |
| Full success | Yes | Yes | Draft only | `published` |

---

## 14. Suggested test fixtures (map to implementation-plan tests)

| Fixture idea | Covers |
| --- | --- |
| Empty CSV, header-only, stale dates, boundary dates | ING-02–03, ING-11 |
| Author/email columns + body email/phone/UPI | ING-08, PII-01–07 |
| 2 reviews only; 3 reviews exactly | VOL-02–03, QTE-15 |
| Model mock returning 7 themes; paraphrased quote; repeated `review_id` | THM-01, QTE-01–03 |
| Body 251 words; planted email in prose; 4th theme in prose | WRT-01, PII-13, THM-05 |
| Tool list including `send_email` | MCP-02 |
| Inclusive window start/end IST vs UTC | ING-11–12 |

Unit tests in Phases 1–5 should cover every **Fail closed** and **Retry** row that does not need live MCP/LLM. Live rows (MCP-04, LLM-01) are Phase 7–8 manual or flagged tests.

---

## 15. Source

- Design and failure modes: `Docs/architecture.md` (§6–8, §13–16)
- Phase gates and stop-ifs: `Docs/implementation-plan.md`
- Product invariants (3/3/3, ≤250 words, public exports, MCP-first, no PII): `Docs/problemStatement.md`
