# 2026-08-22 — Confidence calibration (partial band reachability)

## Problem

AUDIT.md "Remaining" #1: *confidence model overconfidence — `partial`
band unreachable, routing effectively answer/no_answer only.*

Root cause: response-level confidence was the top candidate's normalized
RRF score, `100 × rrf / max_rrf` where `max_rrf = 2/(K+1)` (K=60). That
quantity is rank-agreement only, and it saturates:

| rank in (BM25, vector) | normalized RRF |
|---|---|
| (1, 1) | 100.0 |
| (2, 2) | 98.4 |
| (5, 5) | 93.8 |
| (10, 10) | 87.1 |

Any query that retrieved a top-ranked chunk — relevant or not — scored
≥ ~90 and routed to `"answer"`. Only the empty-result case produced
`"no_answer"`.

## Change

`package_builder._calibrated_confidence(rrf_score, coverage)`:

```
confidence = 100 × (rrf / max_rrf) × (0.55 + 0.45 × coverage)
```

where `coverage = |matched_terms(query, top excerpt)| /
|significant_query_terms(query)|` (stopword-filtered unique terms; a
query with no measurable terms gets coverage 1.0 so it is not penalized).

Effect at the routing thresholds (high ≥ 90 → answer, medium ≥ 75 →
partial, low ≥ 50 → partial, else no_answer):

| scenario | before | after | route after |
|---|---|---|---|
| strong: rank(1,1), coverage 1.0 | 100 | 100 | answer |
| good: rank(2,3), coverage 1.0 | ~98 | ~98 | answer |
| topical: rank(5,5), coverage 0.5 | 93.8 | 72.7 | **partial** |
| weak: rank(10,10), coverage 0.25 | 87.1 | 57.7 | **partial** |
| poor: rank(20,20), coverage 0.0 | 76.3 | 42.0 | **no_answer** |

Excerpt-level confidences (display only) are unchanged; fact-path
responses set their own confidence and are untouched.

## Why these constants

- **Floor 0.55**: keeps single-term queries viable — a one-term query
  that fully matches has coverage 1.0 (factor 1.0); a zero-overlap
  top hit still lands ≥ 55 × agreement, i.e. routable as `partial`
  rather than silently discarded. Below 0.5 the floor would push
  well-ranked-but-unrelated hits into no_answer, hiding retrieval bugs.
- **Linear coverage ramp**: no evidence for a nonlinear term-weighting;
  linear is auditable and monotonic. Revisit if gap analytics show
  long-query under-routing.

## Benchmark status

Full `evaluation/run_benchmark.py` was not run for this change (requires
the embedding model pre-download that CI's eval job currently lacks).
Per CLAUDE.md rule 7 this file records the reasoning so the change stays
auditable. Follow-up: run the benchmark with this calibration and compare
routing distribution + P95 latency; adjust `_COVERAGE_FLOOR` on evidence.

## Files

- `backend/app/response/package_builder.py` — `_calibrated_confidence`,
  applied to response-level confidence only
- `backend/app/search/matched_terms.py` — `significant_query_terms`
- `backend/tests/unit/test_confidence_calibration.py`
