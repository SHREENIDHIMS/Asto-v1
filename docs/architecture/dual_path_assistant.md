# AsTo Dual-Path Assistant — Architecture

> **Gate document for Phase 1.** Read before writing any Phase 1 code.
> Governs the intent-based query router, structured-fact path, document path,
> authorization, and the unified package schema.

## 1. Non-negotiable principles

1. **Strict extractive model.** No LLM-generated facts, no hallucinated text.
   Answers derive ONLY from (a) retrieved document chunks or (b) deterministic
   SQL records. No generative summarization step beyond the existing
   verbatim TextRank extractive summary already approved in CLAUDE.md.
2. **Never mix SQL structured data into unstructured vector context.** The
   vector index contains document chunks only. Structured facts are fetched
   via typed SQL — never embedded, never appended into a prompt, never passed
   through the embedding model.
3. **Authorization before retrieval.** Row-level security parameters
   (`client_id`, `department`, assigned case/client scope) are applied in the
   SQL `WHERE` clause **before execution**. No post-hoc filtering only.
4. **One conversation, one entity.** Conversation context is fixed per active
   Case ID at conversation creation. No mid-conversation entity switching.

## 2. Pipeline overview

```
User query + identity (JWT) + optional case context
        │
        ▼
┌─────────────────────────────────────────────┐
│ 1. Intent-Based Query Router                │
│    classify: STRUCTURED_FACT | DOCUMENT     │
│    (deterministic rules, no LLM)            │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
  ┌──────────────┐ ┌──────────────────────────┐
  │ 2a. Structured │ │ 2b. Document path       │
  │ Fact Path     │ │ (hybrid vector + BM25)   │
  │ typed SQL     │ │ WHERE rbac + is_approved │
  │ lookup scoped │ │                          │
  │ by RLS params │ │                          │
  └──────┬───────┘ └───────────┬──────────────┘
         │                     │
         ▼                     ▼
  ┌─────────────────────────────────────────────┐
  │ 3. Unified Response Package                 │
  │ facts | excerpts | sources | confidence |   │
  │ related_questions | routing | no-answer     │
  └─────────────────────────────────────────────┘
```

## 3. Intent-based query router

Deterministic, rule-driven classifier in `app/query_processing/`
(extends existing `intent_detection.py`). No ML, no LLM.

### Structured-fact intent table

| Intent | Example query | SQL source | RLS scope |
|---|---|---|---|
| `case_status` | "What is the current status of my application?" | `cases.status` + latest `case_events` | `client_id` = caller (client) or assigned case (staff) |
| `case_next_step` | "What happens next?" | latest `case_events` + `workflows` | case scope |
| `missing_documents` | "What documents are still missing?" | documents with `requested`/`pending` status on the case | case scope |
| `case_documents` | "Show me the documents I submitted" | `documents` for the case, approved | case scope |
| `case_property` | "Which property is this for?" | `properties` for the case | case scope |
| `case_timeline` | "What's the history of my case?" | `case_events` ordered | case scope |
| `due_date` | "When is the deadline?" | case/workflow due fields | case scope |
| `workflow_step` | "Where is my file in the process?" | `workflows` + `case_events` | case scope |
| `client_financials` | "What is my loan amount?" | `cases.loan_amount` | case scope |

### Fallback rule
- If a query matches no structured-fact intent (or matches a fuzzy intent
  with no supported fact), it falls through to the **document path**.
- Document path = existing hybrid search (pgvector + BM25) with the RBAC
  filter already in the WHERE clause (`hybrid_orchestrator.py`).

## 4. Structured-fact path

### 4.1 Router contract

```py
# app/query_processing/fact_router.py
@dataclass
class FactRoute:
    intent: str
    resolver: Callable[[Connection, FactContext], list[FactRecord]]

@dataclass
class FactContext:
    user: dict            # decoded JWT claims
    case_id: int | None   # fixed per conversation
    client_id: int | None # resolved from JWT for clients
```

### 4.2 Fact resolution (deterministic SQL)

Each intent maps to one resolver. Example (pseudocode):

```sql
-- case_status resolver (client audience)
SELECT c.case_number, c.status, c.loan_amount,
       (SELECT status FROM case_events e
         WHERE e.case_id = c.id ORDER BY e.created_at DESC LIMIT 1) AS latest,
       (SELECT note FROM case_events e
         WHERE e.case_id = c.id ORDER BY e.created_at DESC LIMIT 1) AS latest_note,
       (SELECT created_at FROM case_events e
         WHERE e.case_id = c.id ORDER BY e.created_at DESC LIMIT 1) AS latest_at
FROM cases c
WHERE c.id = %(case_id)s
  AND c.is_active = true
  AND c.client_id = %(client_id)s   -- ROW-LEVEL SCOPE, always
```

Rules:
- **RLS parameters are bound in SQL before execution**, derived from the JWT
  (never from request body).
- Client → `c.client_id = <jwt.client_id>`.
- Staff → case must belong to an assigned client
  (`staff_client_assignments`) AND match the user's department scope where
  applicable.
- Admin/super_admin → no `client_id` filter (still respect explicit case id).
- Missing/inaccessible case → return a `no_answer` package, never an empty
  or generic fabricated value.

### 4.3 FactRecord → package

Every fact is wrapped with:
- `label` (human field name), `value` (verbatim stored value),
- `source` (table + row id + event id, e.g. `case_events#42`),
- `retrieved_at`.

Facts are displayed as verbatim values with an explicit source line —
identical trust posture to document citations.

## 5. Document path (unchanged core)

- Existing `search_knowledge_base` in `hybrid_orchestrator.py`.
- RBAC + `is_approved`/`is_active` already enforced in the WHERE clause.
- Sub-queries, spelling correction, multi-question split remain untouched.
- Cross-encoder rerank (if enabled) stays under the <200ms p95 budget
  (CLAUDE.md rule 6).

## 6. Unified Response Package schema

Extends the existing `SearchResponse` shape. Both paths emit the same
package. (Frontend types live in `frontend/lib/api-client.ts`.)

```ts
interface ResponsePackage {
  routing: "answer" | "partial" | "no_answer";
  answer: string;                       // always verbatim/extractive only
  sources: SourceRef[];                 // docs AND/OR structured facts
  facts: StructuredFact[];              // populated on fact path
  excerpts: Excerpt[];                  // populated on document path
  confidence: number;                   // 0..1
  related_questions: string[];          // role-scoped
  retrieval_path: "structured_fact" | "document" | "mixed";
  no_answer_reason?: string;            // set only when no_answer
}

interface StructuredFact {
  label: string;
  value: string | number | null;
  source: string;                       // "cases#204" | "case_events#42"
  kind: "status" | "date" | "document" | "amount" | "note" | ...
}

interface SourceRef {
  kind: "document" | "fact";
  id: string;                           // document chunk id OR fact row id
  title?: string;                       // doc title for documents
  ref?: string;                         // "cases#204"
}
```

Rules:
- `answer` is assembled from **retrieved excerpts verbatim** or **fact values
  verbatim** — never rewritten prose.
- `confidence` for the fact path reflects completeness (all fields resolved)
  and may use the existing confidence-threshold routing for `answer` /
  `partial` / `no_answer`.
- `related_questions` must be role-appropriate and context-aware (e.g. a
  client who just learned their status should see "What do I need to do
  next?").

## 7. Authorization matrix (enforced in SQL, not post-hoc)

| Caller | cases | documents | case_events | workflows |
|---|---|---|---|---|
| client | own `client_id` | own + approved | own case | none |
| staff | assigned clients' cases | department + (company-wide OR assigned clients) + approved | assigned cases | department |
| admin/super_admin | all | all | all | all |

## 8. Conversation context

- A chat conversation binds to a `case_id` (staff: from workspace context;
  client: resolved from their case list) at **creation** time.
- Mid-conversation, all fact-path queries reuse that `case_id`.
- Document-path queries additionally receive case-derived context terms
  (case number, client name, property address) for retrieval relevance —
  still fully RBAC-filtered.
- Switching entity = new conversation (explicit UX, no ambiguity).

## 9. Audit & compliance

- Every query (fact or document path) writes to `audit_log` — user, query,
  routing, retrieved IDs, confidence, latency, response id. Fact-path
  retrievals log the SQL rows touched (case/event ids).
- `audit_log` is never skipped, even for test queries against prod data.

## 9a. Multi-question fact resolution (explicitly sanctioned exception)

A single message that contains several questions (e.g. "what's my status?
what's missing?") is split by `query_processing.multi_question` into
`plan.sub_queries`. The fact path now classifies **each sub-query
independently** and resolves **every** matched intent, merging the facts
into ONE `ResponsePackage` (retrieval_path `structured_fact`).

The single-bubble `answer` field is a **deliberate, documented exception**
to the "never assemble sentences from multiple sources" doctrine
(CLAUDE.md §Non-negotiable). It is implemented strictly deterministically:

- Per-intent sentence templates in `fact_path.py` (`_sentences_for_intent`)
  insert each fact's `value` **verbatim** — no paraphrase, no generation.
- A template slot with no fact emits NO sentence (no placeholder text).
- Every fact still carries an explicit source (`cases#204`), rendered under
  the bubble.
- Confidence = mean of per-intent completeness, routed through the shared
  `route_by_confidence` thresholds (answers that are fully covered stay
  `answer`; partially covered get `partial`).
- Sub-questions that match no fact intent are ignored (they fall through to
  the document path message-wide); unrecognized intents never poison the
  supported ones.
- If ANY resolved sub-question is inaccessible (RLS), the whole bubble
  returns `no_answer` — nothing is silently dropped.
- Duplicate intents ("status? also status?") resolve once; identical facts
  are deduplicated.

The document path's `answer` is likewise extractive-only: verbatim summary
sentences joined server-side (no synthesis). Adding any LLM or abstractive
rephrasing here is prohibited without an explicit decision to revisit this
rule.

## 9b. Soft-match routing & clarification (design decision 2026-08-09)

Exact-phrase matching (§3) is a HIGH bar: a client who types "where is my
app at" or "any word on my application" matches nothing literally, so the
router falls back to a deterministic **soft-match stage** in
`fact_router.py` (`route_fact_intent`). It scores every intent as a
weighted blend of fuzzy phrase similarity (`rapidfuzz.partial_ratio`) and
a light keyword-overlap signal — still zero ML, zero LLM.

Asymmetric thresholds (constants, not config — see CLAUDE.md rule 7):

| Constant | Value | Meaning |
|---|---|---|
| `ROUTE_SCORE` | 0.85 | soft match must clear this to route to an intent |
| `ROUTE_MARGIN` | 0.08 | top intent must beat the runner-up by this much |
| `CLARIFY_FLOOR` | 0.30 | weak-but-personal signal → ask, don't guess |

Decision tree, in order:

1. **Fragment guard.** Fewer than 2 words ("status?", "missing?") never
   route — no guessing from a bare fragment.
2. **Exact phrase** → route at confidence 1.0.
3. **Decisive soft winner** (score ≥ `ROUTE_SCORE` and ahead by
   `ROUTE_MARGIN`) → route to that intent.
4. **Personal gray zone.** Score ≥ `CLARIFY_FLOOR`, the query is phrased
   about the caller's own case (`_PERSONAL_RE`: "my case/app/loan/…",
   "do you need", "from me"), and it does NOT map to a hard document-path
   intent (`_HARD_DOC_INTENTS`: eligibility / costs / limits / definition)
   → return a **clarifying prompt** instead of best-guessing.
5. Otherwise → fall through to the document path.

**Why ask instead of best-guess.** Routing a query to a fact intent is a
high-stakes act — the answer is a *stored value* ("$240,000", "in
underwriting") shown as authoritative. Guessing wrong is worse than
saying "I'm not sure". For genuinely ambiguous personal questions the
caller returns `_clarify_package`: routing `no_answer`, a FIXED
deterministic prompt in `no_answer_reason`, and the intent's example
questions in `related_questions` so the frontend renders them as
click-to-ask chips (no new UI plumbing).

**Never clarified:** conditional/hypothetical phrasing ("what happens if i
miss a payment") is policy, not this caller's case; generic reference
questions (eligibility, costs, limits, definitions) belong to the document
path by construction. "documents"/"requirements" are deliberately excluded
from `_HARD_DOC_INTENTS` because they overlap with legitimate personal
questions ("do you need my w2?" → missing-documents).

**Spell-correction protection (same decision).** Real-word swaps were
observed: the valid English word "borrow" was being corrected into the
domain term "borrower", and the typo "wats" into "was". The correction
vocabulary (`domain_terms.py` `COMMON_WORDS`) now includes common
conversational query vocabulary (verbs and tenses: borrow/owe/pay/upload/
submit/send/check/…, plus personal pronouns and filler), so valid English
words are treated as protected vocabulary instead of fuzzy-matching a
domain term. Phonetic contractions ("wats"/"wut" → "what is") are expanded
in `normalization.py`. Typos that are NOT valid words (e.g. "ammount",
"requirment", "cred") are still corrected.

## 9c. Mention-based case resolution (universal search, design decision 2026-08-10)

When a query has no explicit `case_id` and the caller has no
auto-resolvable case, the fact path now tries to find the case the user is
*talking about* from entity mentions in the query text
(`query_processing/case_resolver.py`):

- **Case number** — `CAS-2026-0001` (full form) or a short form
  `CAS-0001` / `cas_0001` (letters + hyphen/underscore + digits), which is
  resolved against stored numbers by letter-prefix + digit-suffix matching
  so a partial number without the year still lands precisely. A bare space
  is never treated as a case-number separator ("is 2026", "case 1" are not
  mentions).
- **Property address** — street-name token match with a street-number
  tie-break ("99 factpath ave" uniquely selects 99 Factpath Ave even when
  77 Factpath Ave shares the street name); city name is a fallback signal.
- **Client name** — full-name match ("for client two" requires both
  tokens; a bare "client" never matches).

Resolution order: case-number mention → property mention → client-name
mention → explicit `case_id` (the UI's case-context dropdown) → client
auto-resolve (most recent active case) → fall through. An entity mention
in the current query text wins over the dropdown: the dropdown is a
default context, but "what's the loan on 456 oak ave?" names the case the
user means *now*, and the candidate-case chips re-ask with a case number
appended — both would be silently overridden if the dropdown always won.
When a mention is ambiguous AND the selected case is one of the
candidates, the dropdown disambiguates; otherwise the caller is offered
candidate-case chips.

**No selection, no mention → answer anyway (design decision 2026-08-10).**
An end user (staff especially) often cannot reliably pick the right case
from a dropdown, so the assistant must not dead-end on "I need a case
selected to answer that." when a determinable answer exists. When the
caller has no explicit case and no resolvable mention, the fact path
auto-resolves a caller with exactly **one** accessible active case, and
offers the accessible active cases as suggestion chips when there are
**several** (same RLS scope — never widens access). Only a caller with
zero accessible active cases falls through to the "select a case" prompt.

**RLS is bound in the SQL `WHERE` clause** (`_accessible_case_rows` uses
the same `_case_scope` as every resolver): the candidate set is always the
caller's own cases (client), assigned clients' cases (staff), or all cases
(admin). Mention resolution never widens access — it only picks a case from
the set the caller could already see.

**Ambiguity → candidate-case chips.** When several cases match, the caller
returns a `no_answer` package whose related-question chips re-ask the SAME
question with the candidate case number appended ("… for case CAS-2026-0001").
Clicking a chip re-enters mention resolution, the case-number mention wins,
and the fact path resolves deterministically. Chips are fixed templates
whose only variable is a stored case number — no generated text.

## 10. Testing gate

- Unit: `fact_router` classification, each resolver's RLS behavior (client
  cannot read another client's case; staff cannot read unassigned case).
- Integration: end-to-end fact query for a seeded client; document fallback
  for non-fact queries.
- Benchmark: run `evaluation/run_benchmark.py` before/after any change to
  ranking or packaging; record delta in `evaluation/reports/`.
