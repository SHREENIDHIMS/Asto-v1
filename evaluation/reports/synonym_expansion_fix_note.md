# Benchmark note — synonym expansion fix (audit #23 / 3.3)

Date: 2026-08-21

## Change
`hybrid_orchestrator.py`:
- Fixed `_expand_query_with_synonyms` row access (dict rows were unpacked
  by iteration, yielding the literal keys `canonical`/`alias`, so no alias
  ever matched — the feature was non-functional).
- `combined_text` is now built from the **expanded** primary query, so the
  BM25 tsquery receives the expansion (previously only the embedding did).
- The `synonyms` table is cached (60s TTL) with inline invalidation from
  the admin create/delete endpoints instead of a full-table fetch per
  request.

## Benchmark decision (CLAUDE.md rule 7)
A full before/after benchmark was **not run**: the production/dev
`synonyms` table is empty (verified `SELECT count(*) FROM synonyms` → 0),
so expansion is a no-op in the current environment — `build_tsquery` and
`embed_query` receive byte-identical input before and after the change,
and retrieval metrics are expected to be identical.

When synonyms are populated, the change activates expansion for both the
tsquery and the embedding; that activation should be benchmark-verified
at that time. Re-run: `python -m evaluation.run_benchmark --output-dir
evaluation/reports` before/after seeding synonyms, and record the delta.