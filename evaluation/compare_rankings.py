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
from app.ranking.rrf import rank_fusion
from app.db.postgres.session import acquire

USER = {
    "id": "benchmark",
    "role": "super_admin",
    "departments": ["general"],
    "allowed_departments": ["general"],
}

WEIGHT_SWEEP = [(round(b / 10, 1), round(1 - b / 10, 1)) for b in range(0, 11)]


def rank_linear(candidates, w_b: float, w_v: float) -> list[int]:
    scored = [(c.chunk_id, w_b * c.bm25_score + w_v * c.vec_score) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in scored]


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
