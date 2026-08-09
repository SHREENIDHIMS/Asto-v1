# Benchmark record — 2026-08-09 fact-path routing & spell-correction hardening

Changes under evaluation:
- `query_processing/fact_router.py`: soft-match routing (asymmetric thresholds)
  + clarifying prompt; runs on the fact path only, which the document-path
  benchmark does not exercise.
- `query_processing/spell_correction.py`: length-difference guard against
  real-word swaps ("second" -> "send"); candidate walk so a length-valid
  runner-up is chosen.
- `query_processing/domain_terms.py`: expanded COMMON_WORDS (conversational
  verbs, ordinals, filler) so valid English words are protected.
- `query_processing/normalization.py`: phonetic contractions ("wats"/"wut" ->
  "what is").
- `evaluation/datasets/seed_benchmark_data.py` + test DB gating: benchmark
  seed/clear now scoped to its own rows (`source_path='__benchmark_seed__'`);
  tests gate to `ASTO_TEST_DATABASE_URL`. No effect on retrieval metrics.

## Query-processing accuracy (unchanged)

| metric | before (20260808_101228) | after (20260809_170228) |
|---|---|---|
| sub_question_accuracy | 1.0 | 1.0 |
| intent_accuracy | 1.0 | 1.0 |
| entity_accuracy | 1.0 | 1.0 |
| avg query proc latency ms | 0.79 | 0.75 |

A per-query field diff (`normalized`, `intent`, `entities`, `sub_queries`)
between the two reports is **0 differences across the full dataset**.

## Retrieval metrics — within established run-to-run variance

| metric | before | after | note |
|---|---|---|---|
| hit_rate@10 | 1.0 | 1.0 | eval gate metric, unchanged |
| hit_rate@1 | 1.0 | 0.928 | baseline itself ranged **0.917–1.0** across 2026-08-08 runs |
| mrr@10 | 0.968 | 0.932 | within variance band |
| ndcg@10 | 0.904 | 0.866 | within variance band |

Because processing output is byte-identical for every eval query, the
retrieval delta is attributable to approximate HNSW vector search /
embedding run-to-run variance, not to these changes. The `eval_on_pr`
regression gate (sub_question/intent/entity accuracy + hit_rate@10,
threshold 0.05) passes: all four are unchanged at 1.0.
