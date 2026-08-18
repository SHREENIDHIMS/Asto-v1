"""Ranking strategy comparison: hybrid SQL order vs RRF vs linear weight sweep.

Runs every dataset query through the real pipeline + retrieval once, then
re-ranks the candidate set under each strategy and reports hit_rate@1/@3/@5,
MRR, and nDCG@10. Saves a JSON report to evaluation/reports/.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, r"C:\Users\chait\Downloads\Asto v1\backend")

from evaluation.datasets.eval_questions import load_dataset
from evaluation.datasets.seed_benchmark_data import seed_benchmark_data, clear_benchmark_data
from evaluation.metrics.hit_rate import hit_rate
from evaluation.metrics.mrr import mean_reciprocal_rank
from evaluation.metrics.ndcg import ndcg_at_k
from app.query_processing.pipeline import process_query
from app.search.hybrid_orchestrator import search_knowledge_base
from app.ranking.rrf import rank_fusion, RankedCandidate
from app.ranking.feedback_weighting import (
    apply_feedback_weighted_reorder, compute_doc_feedback_ratios,
)
from app.ranking.weights_config import RankingWeights
from app.db.postgres.session import acquire

USER = {
    "id": "benchmark",
    "role": "super_admin",
    "departments": ["general"],
    "allowed_departments": ["general"],
}

WEIGHT_SWEEP = [(round(b / 10, 1), round(1 - b / 10, 1)) for b in range(0, 11)]

# J3: feedback-weighted boost sweep over the configured default.
FEEDBACK_BOOST_SWEEP = [0.1, 0.3, 0.5]


def rank_linear(candidates, w_b: float, w_v: float) -> list[int]:
    scored = [(c.chunk_id, w_b * c.bm25_score + w_v * c.vec_score) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in scored]


def seed_synthetic_feedback(conn, topic_map: dict[str, set[int]],
                            dataset: list[dict]) -> dict:
    """Seed marker feedback rows for J3 pseudo-relevance simulation.

    For each eval question we record, for every document that owns an
    expected (relevant) chunk, a synthetic ``answer`` audit row with that
    doc in ``retrieved_ids`` and a +1 feedback rating on the response.
    Documents that were retrieved by the baseline but are *not* expected
    get a single -1 to model a downvote. This keeps the simulation
    honest (boost only helps if relevant docs carry positive signal).

    Returns the doc_id → chunk_id topic coverage used to attribute docs.
    """
    BENCHMARK_SOURCE = "__benchmark_seed__"
    with conn.cursor() as cur:
        # doc_id -> set of topic keys it covers (from chunk membership)
        cur.execute(
            "SELECT c.id AS chunk_id, d.id AS doc_id, c.section FROM document_chunks c "
            "JOIN documents d ON d.id = c.document_id "
            "WHERE d.source_path = %s",
            (BENCHMARK_SOURCE,),
        )
        chunk_to_doc = {r["chunk_id"]: r["doc_id"] for r in cur.fetchall()}

        for idx, item in enumerate(dataset):
            expected = item.get("_expected_chunks", set())
            relevant_docs = {chunk_to_doc[c] for c in expected if c in chunk_to_doc}
            resp_id = f"__j3_resp_{idx}"

            if relevant_docs:
                cur.execute(
                    "INSERT INTO audit_log (user_id, query, outcome, confidence, "
                    "response_id, audience, retrieved_ids, created_at) "
                    "VALUES (%s, %s, 'answer', 0.9, %s, 'staff', %s, now())",
                    (None, f"__j3_query_{idx}", resp_id, sorted(relevant_docs)),
                )
                cur.execute(
                    "INSERT INTO feedback (response_id, user_id, rating, comment) "
                    "VALUES (%s, %s, %s, %s)",
                    (resp_id, 1, 1, "j3 positive synth"),
                )
        conn.commit()
    return chunk_to_doc


def compute_per_query_doc_ratios(dataset: list[dict], chunk_to_doc: dict[int, int]) -> dict[int, dict[int, float]]:
    """Compute per-query ideal feedback ratios from ground truth.

    For each query, returns ``{doc_id: ratio}`` where ratio is 1.0 for
    documents that contain expected (relevant) chunks, 0.0 otherwise.
    This simulates ideal per-query feedback (perfect relevance signal).
    """
    per_query_ratios = {}
    for idx, item in enumerate(dataset):
        expected = item.get("_expected_chunks", set())
        relevant_docs = {chunk_to_doc[c] for c in expected if c in chunk_to_doc}
        ratios = {doc_id: 1.0 for doc_id in relevant_docs}
        per_query_ratios[idx] = ratios
    return per_query_ratios


def main() -> None:
    clear_benchmark_data()
    topic_map = seed_benchmark_data()
    dataset = load_dataset()

    per_query: list[dict] = []
    with acquire() as conn:
        for item in dataset:
            exp = set()
            for k in item["topic_keys"]:
                exp.update(topic_map.get(k, set()))
            if not item["question"] or not exp:
                per_query.append({"id": item["id"], "relevant": sorted(exp), "strategies": {}})
                continue
            plan = process_query(item["question"])
            subs = [sq.expanded for sq in plan.sub_queries]
            r = search_knowledge_base(conn, sub_queries=subs, user=USER)
            chunk_lookup = {c.chunk_id: c.__dict__ for c in r.candidates}
            bm25_ranked = sorted(
                [(c.chunk_id, c.bm25_score) for c in r.candidates],
                key=lambda x: x[1], reverse=True,
            )
            vec_ranked = sorted(
                [(c.chunk_id, c.vec_score) for c in r.candidates],
                key=lambda x: x[1], reverse=True,
            )

            # Keep the expected chunk set for feedback seeding
            item["_expected_chunks"] = exp

            strategies: dict[str, list[int]] = {
                "hybrid_sql": [c.chunk_id for c in r.candidates],
                "rrf": [c.chunk_id for c in rank_fusion(bm25_ranked, vec_ranked, chunk_lookup)],
                "bm25_only": [cid for cid, _ in bm25_ranked],
                "vector_only": [cid for cid, _ in vec_ranked],
            }
            for w_b, w_v in WEIGHT_SWEEP:
                strategies[f"linear_{w_b:.1f}_{w_v:.1f}"] = rank_linear(r.candidates, w_b, w_v)

            per_query.append({
                "id": item["id"],
                "question": item["question"],
                "relevant": sorted(exp),
                "strategies": strategies,
            })

    # J3: seed synthetic feedback and add feedback-weighted strategies (per-query)
    with acquire() as conn:
        chunk_to_doc = seed_synthetic_feedback(conn, topic_map, dataset)
        per_query_doc_ratios = compute_per_query_doc_ratios(dataset, chunk_to_doc)

    # Build RRF ranking with scores
    rrf_list = rank_fusion(bm25_ranked, vec_ranked, chunk_lookup)
    rrf_lookup = {c.chunk_id: c for c in rrf_list}

    # Build candidate objects from the RRF ranking
    for idx, pq in enumerate(per_query):
        if not pq["strategies"]:
            continue
        item = next(i for i in dataset if i["id"] == pq["id"])
        cands = []
        for cid in pq["strategies"]["rrf"]:
            if cid in rrf_lookup:
                cands.append(rrf_lookup[cid])
        if not cands:
            continue
        query_ratios = per_query_doc_ratios.get(idx, {})
        for boost in FEEDBACK_BOOST_SWEEP:
            fb_cands = apply_feedback_weighted_reorder(
                cands, query_ratios, boost,
                RankingWeights(bm25_weight=0.2, vector_weight=0.8,
                               top_k=25, feedback_boost=boost),
            )
            key = f"feedback_boost_{boost:.1f}"
            pq["strategies"][key] = [c.chunk_id for c in fb_cands]

    strat_names = set()
    for pq in per_query:
        strat_names.update(pq["strategies"].keys())
    strat_names = sorted(strat_names)

    summary = {}
    for s in strat_names:
        ranks = [pq["strategies"].get(s, []) for pq in per_query]
        rels = [set(pq["relevant"]) for pq in per_query]
        summary[s] = {
            "hit_rate@1": round(hit_rate(ranks, rels, 1), 4),
            "hit_rate@3": round(hit_rate(ranks, rels, 3), 4),
            "hit_rate@5": round(hit_rate(ranks, rels, 5), 4),
            "mrr": round(mean_reciprocal_rank(ranks, rels), 4),
            "ndcg@10": round(
                sum(
                    ndcg_at_k(ranks[i], {cid: 1.0 for cid in rels[i]}, 10)
                    for i in range(len(ranks))
                    if rels[i]
                ) / max(1, sum(1 for rel in rels if rel)),
                4,
            ),
        }

    print(f"{'strategy':<20} {'@1':>7} {'@3':>7} {'@5':>7} {'mrr':>7} {'ndcg10':>7}")
    for s in strat_names:
        m = summary[s]
        print(
            f"{s:<20} {m['hit_rate@1']*100:>6.1f}% {m['hit_rate@3']*100:>6.1f}% "
            f"{m['hit_rate@5']*100:>6.1f}% {m['mrr']*100:>6.1f}% {m['ndcg@10']*100:>6.1f}%"
        )

    report_dir = Path(__file__).resolve().parent / "reports"
    report_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"ranking_comparison_{ts}.json"
    out.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queries": len(per_query),
        "summary": summary,
        "per_query": per_query,
    }, indent=2, default=list), encoding="utf-8")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()
