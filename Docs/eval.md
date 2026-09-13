# Evaluation: Groww Weekly Review Pulse

How we prove each **exit criterion** in `Docs/implementation-plan.md` and the problem-statement **definition of done**. Evals are the gate between phases: a phase is not complete until its suite below is green.

Two tracks run in parallel after Phase 4:

| Track | Trusts the LLM? | When | Gate |
| --- | --- | --- | --- |
| **A — Invariants** | No | Every phase | CI; 100% pass required |
| **B — Pulse quality** | Optional judge / human | Phases 6 and 8 | Content-freeze and “project done” |

Invariants (quotes, PII, theme cap, word count, MCP-first, draft-not-send) **never** depend on a model score. Quality evals cannot override a failed invariant.

---

## 1. What “eval” means here

| Kind | Mechanism | Examples |
| --- | --- | --- |
| Unit / contract | `pytest` | Schema, ingest window, PII, quote substring, validator |
| Graph | `pytest` + fixture invoke | Empty input → `failed`; retry then stop; MCP skipped in Phase 6 |
| Golden snapshot | Diff structured fields + shape regex | Fixture → expected theme count, 3/3/3, ≤250 words |
| Live Groq (optional) | Same validators on real Groq output | Phase 6 snapshot |
| Human rubric | Scorecard in §6 | Scannable, Groww-relevant, actions concrete |
| MCP smoke | Flagged (`PULSE_MCP=1`) | Doc exists, draft exists, mail not sent |
| Policy | Static / grep | No `googleapis.com` REST client in `src/` |

---

## 2. Pass bars

| Suite | Pass bar | Fail policy |
| --- | --- | --- |
| Phase 0–5 invariant tests | **100%** | Block the next phase |
| Phase 6 snapshot invariants | **100%** on fixture; **100%** on any live run used as freeze | No MCP until freeze |
| Phase 6 quality rubric (human) | **≥ 3 / 4** on every dimension in §6, no dimension at 1 | Re-run write/cluster; do not lower the bar |
| Phase 7 allow-list tests | **100%** | Block Phase 8 |
| Phase 7 live MCP | **Pass** when flag set; **skip** in CI if unset | CI must still be green |
| Phase 8 E2E checklist | **All six** success criteria | Project not done |

Do not use “average quality” to hide a PII leak or an invented quote.

---

## 3. Eval assets

Create these as the plan’s tests come online. Paths match the implementation plan.

```text
tests/
├── fixtures/
│   ├── reviews_sample.json          # both stores, inside window, no real PII
│   ├── reviews_stale.json           # all dates outside window
│   ├── reviews_pii_planted.json     # email, IN phone, username, device id
│   ├── reviews_two_only.json        # VOL-02: cannot support 3 quotes
│   ├── reviews_boundary.json        # window start/end, IST vs UTC
│   └── pulse_invalid_*.md           # 251 words, extra theme, planted email, paraphrase
├── test_schemas.py
├── test_ingest.py
├── test_privacy.py
├── test_graph_skeleton.py
├── test_quotes.py
├── test_cluster_cap.py
├── test_validate.py
├── test_mcp_allowlist.py
└── eval/
    ├── test_snapshot_invariants.py  # Phase 6
    └── rubric_phase6.md             # filled by human at freeze
```

**Fixture rules**

- No real reviewer names, emails, or device IDs.
- Planted PII uses obviously fake values (`alice@example.com`, `+91 90000 00000`).
- Include Play and App Store rows, ratings 1–5, `en_IN`, Groww package id.
- Enough rows in `reviews_sample.json` for 3 distinct quotes (≥ 5 reviews recommended).

---

## 4. Track A — phase-wise invariant evals

Each subsection is the **eval contract** for that implementation-plan phase. Mapping: plan “Must-have tests” table → cases below.

### Phase 0 — Foundation

**Command:** `pytest tests/test_schemas.py tests/test_config.py -q` (add `test_config.py` if config is separate)

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E0-01 | `pip install -e .` | Exit 0 |
| E0-02 | Config loads `com.nextbillion.groww`, `en_IN`, weeks in 8–12, limits 5 / 3 / 3 / 3 / 250, `llm.provider=groq` | Exact |
| E0-03 | `RawReview` has no author/username field | AttributeError / schema exclude |
| E0-04 | `PulseNote` with 4 quotes or 2 actions is rejected | Validation error |
| E0-05 | `.env.example` has `GROQ_API_KEY` only; no OpenAI or Google token keys | Grep |
| E0-06 | `data/raw/` and `.env` gitignored | Pattern present |

**Live Groq / MCP:** No.

### Phase 1 — Ingest

**Command:** `pytest tests/test_ingest.py -q`

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E1-01 | `reviews_sample.json` yields `rating`, text or title, `date`, `store` | All rows |
| E1-02 | Dates outside window excluded | Stale fixture → 0 kept, fail closed if that is the only file |
| E1-03 | Empty / whitespace bodies dropped | Count decreases |
| E1-04 | Author/email/device columns not on `RawReview` | Even if present in CSV |
| E1-05 | Window start and end dates **included** | Boundary fixture |
| E1-06 | Non-Groww package rows dropped | Mixed export |
| E1-07 | Invalid ratings (0, 6, `"five"`) dropped | |
| E1-08 | Play + App Store merge tags `store` correctly | Both values present |
| E1-09 | Empty or header-only file fails closed with a parse/empty error | Not a silent `[]` without error if it was the sole source |

**Stop eval:** If ingest only works via login scraping, Phase 1 **fails** regardless of tests (plan stop-if).

**Live Groq / MCP:** No.

### Phase 2 — Privacy

**Command:** `pytest tests/test_privacy.py -q`

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E2-01 | Planted email/phone/username/device absent from `SanitizedReview.text` and `.title` | |
| E2-02 | `review_id` ≠ store source id; opaque hash | |
| E2-03 | Attribution helper is `(N★, Play Store\|App Store, YYYY-MM-DD)` with no name | Regex |
| E2-04 | All-empty after sanitize → no reviews passed to cluster | Tested in Phase 3 as well |
| E2-05 | Suite runs **without** LLM | No network to model APIs |

**Live Groq / MCP:** No.

### Phase 3 — Graph skeleton

**Command:** `pytest tests/test_graph_skeleton.py -q`

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E3-01 | Graph compiles | |
| E3-02 | Fixture run fills `state.reviews` after `SanitizePII` | |
| E3-03 | Empty / all-dropped input → `status=failed`, cluster **not** invoked | Mock/spy |
| E3-04 | Downstream stubs do not crash | |

**Live Groq / MCP:** No.

### Phase 4 — Intelligence (mocked Groq)

**Command:** `pytest tests/test_quotes.py tests/test_cluster_cap.py -q`

Mocks return structured JSON. **No live model required to pass the phase.**

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E4-01 | Mock returns 7 themes → persisted clusters **≤ 5** | |
| E4-02 | Nominated paraphrase / extra words → rejected; copy is substring of sanitized text | |
| E4-03 | Exactly 3 quotes, 3 distinct `review_id`s | |
| E4-04 | Exactly 3 actions; each `theme` ∈ cluster names | |
| E4-05 | Body matches three-section template (title + themes + quotes + actions) | Regex/headings |
| E4-06 | Quote tests do not call a live model | Patch/mock assert |

**Live Groq:** Optional smoke only; does not gate Phase 4.

### Phase 5 — Guardrails

**Command:** `pytest tests/test_validate.py tests/test_graph_retry.py -q`

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E5-01 | 251+ words → fail | |
| E5-02 | Missing heading / ≠ 3 themes, quotes, or actions in **prose** → fail | |
| E5-03 | Quote in body not ⊆ any `SanitizedReview` → fail | |
| E5-04 | Planted email in body → fail | |
| E5-05 | Theme in prose not in `clusters` or 6th theme → fail | |
| E5-06 | Fail → `WritePulse` retried; MCP **not** called | Spy |
| E5-07 | After N write failures → `status=failed`, `errors[]` non-empty, no publish | |
| E5-08 | Valid pulse → validator pass (fixture of a known-good ≤250 word note) | |

Word count must use the **same tokenizer** as production (whitespace split; document in `validate.py`).

**Live Groq / MCP:** No.

### Phase 6 — Local snapshot (content freeze)

**Commands:**

```text
pytest tests/eval/test_snapshot_invariants.py -q
python -m pulse.run   # fixture and, if present, real public export
```

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E6-01 | CLI prints `run_id`, theme names, word count, snapshot path | |
| E6-02 | Snapshot: top 3 themes, 3 attributed quotes, 3 actions | |
| E6-03 | Word count ≤ 250 | |
| E6-04 | No PII patterns in snapshot | Reuse privacy regex |
| E6-05 | Each quoted string ⊆ sanitized reviews from that run | |
| E6-06 | `status=ready`; PublishDoc/DraftEmail skipped (not `published`) | |
| E6-07 | Human rubric §6 on that snapshot | ≥ 3/4 all dimensions |

**Content freeze:** Phase 7 does not start until E6-01–07 pass on **one** scanned snapshot.

**Live Groq:** Optional but expected for freeze. Fixture-only freeze is allowed if the fixture is realistic (≥ 5 reviews, mixed ratings). Calls go to Groq (`GROQ_API_KEY`), not OpenAI.

### Phase 7 — MCP

**Commands:**

```text
pytest tests/test_mcp_allowlist.py -q
PULSE_MCP=1 pytest tests/eval/test_mcp_smoke.py -q   # skipped unless flag
```

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E7-01 | Bound tools exclude send-mail names (`send`, `messages.send`, etc.) | |
| E7-02 | `src/` has no Google OAuth client and no `googleapis.com` REST usage | Grep / ast |
| E7-03 | (Flag) Doc titled `Groww Weekly Review Pulse — {start} to {end}` exists via MCP | |
| E7-04 | (Flag) Gmail **draft** to `operator.email`; **not** sent | |
| E7-05 | (Flag) Draft body is full note **or** contains Doc URL | |
| E7-06 | CI without flag: allow-list tests run; smoke skipped; suite green | |

**Stop eval:** MCP unavailable → Phase 7 live cases skip; do **not** pass E7-03 by using a Google API client.

### Phase 8 — Hardening / done

| Eval ID | Checks | Pass |
| --- | --- | --- |
| E8-01 | Second run, same window: **one** Doc updated, not a second title | |
| E8-02 | Empty export and all-PII-empty: clear `failed`, no Doc | |
| E8-03 | Docs OK + Gmail missing: Doc remains; status reports both | |
| E8-04 | Logs contain `review_id` hashes only (no email/author) | |
| E8-05 | Walk §5 success checklist on real public 8–12 week data | All six boxes |

**Live Groq and MCP:** Yes.

---

## 5. Success-criteria eval map

From the implementation-plan traceability table: each problem-statement box is **proven** by the eval IDs below.

| Success criterion | Proven by |
| --- | --- |
| Import ~8–12 weeks public reviews | E1-*, E6-01, E8-05 |
| Cluster ≤ 5 themes | E4-01, E5-05, E6-02 |
| Top 3 themes, 3 quotes, 3 actions | E4-03–05, E5-02, E6-02 |
| ≤ 250 words, scannable, no PII | E2-*, E5-01, E5-04, E6-03–04, §6 Scan |
| Google Docs via MCP | E7-02–03, E8-01, E8-05 |
| Gmail draft via MCP | E7-01, E7-04–05, E8-03, E8-05 |

---

## 6. Track B — pulse quality rubric (Phases 6 and 8)

Used only **after** Track A invariants pass. Score 1–4. Freeze requires **≥ 3 on every row**.

| Dimension | 1 — Fail | 2 — Weak | 3 — Pass | 4 — Strong |
| --- | --- | --- | --- | --- |
| **Themes (Product)** | Generic (“bugs”) or not in the reviews | Plausible but miss the obvious volume driver | Top themes match what a reader would see skimming the fixture/export | Themes named as Groww surfaces (KYC, add money, withdrawals, …) with volume or rating signal |
| **Quotes (truth)** | Invented or cleaned-up wording | Verbatim but all from one theme or unattributed | 3 verbatim, attributed, distinct reviews | Quotes illustrate the top 3 themes without extra editorializing |
| **Actions (next step)** | Slogans (“improve UX”) | Vague owners or not tied to a theme | Concrete step + theme + Product/Support/Growth | A PM could file a ticket from the line as written |
| **Scan (Leadership)** | Wall of text or missing section | Has sections but dense | Three headed sections, ≤250 words, readable in one minute | Title window obvious; numbers (counts/stars) without clutter |
| **Audience fit** | Only rant or only praise | One audience served | Product, Support, and Leadership each get a signal | Actions map cleanly to the three audiences in the problem statement |

Record scores in `tests/eval/rubric_phase6.md`:

```text
Run ID:
Window:
Scorer:
Themes: /4
Quotes: /4
Actions: /4
Scan: /4
Audience: /4
Freeze: yes/no
Notes:
```

**Judge-LLM (optional):** A second **Groq** call may score the same rubric for regression, but a **human** freeze is required once (Phase 6 exit). Automated judge scores are advisory. Do not use OpenAI as the judge.

---

## 7. Suggested pytest markers

```text
pytest -m "not live_llm and not live_mcp"   # default CI
pytest -m live_llm                          # Phase 6 optional
PULSE_MCP=1 pytest -m live_mcp              # Phase 7 smoke
```

| Marker | Phases | CI default |
| --- | --- | --- |
| (none / invariant) | 0–5, 7 allow-list | Run |
| `live_llm` | 6 | Skip |
| `live_mcp` | 7–8 | Skip |

This matches the plan’s “Live LLM / Live MCP” columns (live LLM = Groq).

---

## 8. CI vs local matrix

| Environment | Runs | Must be green to merge |
| --- | --- | --- |
| CI | E0–E5, E7-01, E7-02, E7-06 | Yes |
| Local Phase 6 freeze | E6-01–07 + rubric | Yes before MCP work |
| Local Phase 7 | E7-03–05 with flag | Yes before calling the project done |
| Local Phase 8 | E8-01–05 | Yes for definition of done |

---

## 9. Eval anti-patterns (do not count as pass)

- Mocking `ValidatePulse` to always succeed so a live demo can publish
- Using paraphrased quotes in a “golden” snapshot
- Counting a sent Gmail message as success (draft only)
- Pointing at a Doc created by hand in the Google UI
- Lowering `max_words` or theme cap in config to make tests pass
- Checking in real `data/raw/` exports with PII as fixtures
- Calling `api.openai.com` or checking in `OPENAI_API_KEY`

---

## 10. Definition of done (eval view)

The project is **eval-complete** when:

1. Default CI (no live LLM/MCP) is green.
2. One Phase 6 snapshot has passed invariants **and** the human rubric freeze.
3. Flagged MCP smoke shows a Doc and a **draft** (not send), MCP-first (E7-02).
4. Phase 8 checklist E8-05 is ticked against real public 8–12 week Groww reviews.

That is the same outcome as implementation-plan Phase 8 exit criteria, stated as measurable evals.

---

## Source

- Phase gates, test order, stop-ifs: `Docs/implementation-plan.md`
- Invariants and node contracts: `Docs/architecture.md`
- Product success criteria: `Docs/problemStatement.md`
- Case IDs to expand fixtures: `Docs/edge-case.md`
