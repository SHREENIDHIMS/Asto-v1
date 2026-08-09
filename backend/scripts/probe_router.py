"""Ad-hoc sanity harness for the fact router + spell fixes.

Usage: python scripts/probe_router.py
Runs a list of queries through the fact path / document path and prints
the routing decision for each.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.query_processing.fact_router import route_fact_intent
from app.query_processing import spell_correction as sc
from app.query_processing import normalization as norm


QUERIES = [
    # --- Routes to a fact intent via soft match (should show an intent) ---
    "where is my app at",
    "any word on my application",
    "whats happening with my app",
    "did you get my documents",
    "do you need my w2",
    "how much did i borrow",
    "what about my house",
    "is my loan being processed",
    # --- Clarify prompt (ambiguous, personal) ---
    "is my payment late",
    "whats going on with my loan",
    # --- Document path (must NOT route / clarify) ---
    "can i get a loan with 620 score",
    "what is the interest rate",
    "what happens if i miss a payment",
    "what documents do i need to apply",
    # --- Spell correction real-word protection ---
    "wats my loan ammount",
    "how much did i borrow",
    "what is the down payment for a second home",
    "cred score requirment",
]


def main() -> None:
    print(f"{'QUERY':<46} | {'INTENT':<14} | CLARIFY | corrected")
    print("-" * 100)
    for q in QUERIES:
        r = route_fact_intent(norm.normalize(q))
        corrected = sc.correct(norm.normalize(q))
        print(
            f"{q:<46} | {str(r.intent or '-'):<14} | "
            f"{str(r.needs_clarification):<7} | {corrected}"
        )


if __name__ == "__main__":
    main()
