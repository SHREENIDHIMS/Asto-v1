"""Mortgage domain vocabulary.

A single, curated source of truth for three deterministic behaviours:

1. **Typo correction** — the vocabulary gates which tokens may be
   corrected, so domain terms, acronyms, numbers and percentages are
   never "corrected" away.
2. **Entity extraction** — aliases map onto canonical terms with a type.
3. **Query expansion** — aliases/acronyms expand into their canonical
   phrase so both BM25 and the embedding model see richer text.

Canonical key = canonical phrase. ``aliases`` = accepted surface forms
(abbreviations, acronyms, common variants, plurals). Everything is
lowercase — normalization lowercases before these tables are used.
"""

from __future__ import annotations

import re

# term_type values:
#   lender / program, product, document, property, metric, process, status
DOMAIN_TERMS: dict[str, dict] = {
    # --- Lenders / programs ---
    "federal housing administration": {
        "type": "lender",
        "aliases": ["fha", "fha loan", "fha loans"],
    },
    "veterans affairs": {
        "type": "lender",
        "aliases": ["va", "va loan", "va loans", "veterans administration"],
    },
    "united states department of agriculture": {
        "type": "lender",
        "aliases": ["usda", "usda loan", "usda loans"],
    },
    "conventional": {
        "type": "lender",
        "aliases": ["conventional loan", "conventional loans", "conforming loan", "conforming"],
    },
    "jumbo": {
        "type": "lender",
        "aliases": ["jumbo loan", "jumbo loans", "non conforming", "non-conforming"],
    },
    "fannie mae": {"type": "lender", "aliases": ["fannie mae", "fnma"]},
    "freddie mac": {"type": "lender", "aliases": ["freddie mac", "fhlmc"]},
    "fha 203k": {"type": "product", "aliases": ["203k", "203k loan", "fha 203k"]},

    # --- Products ---
    "adjustable rate mortgage": {
        "type": "product",
        "aliases": ["arm", "arms", "adjustable rate", "adjustable-rate mortgage", "adjustable rate mortgage"],
    },
    "fixed rate mortgage": {
        "type": "product",
        "aliases": ["fixed rate", "fixed-rate", "fixed rate mortgage", "fixed-rate mortgage"],
    },
    "helic home equity line of credit": {
        "type": "product",
        "aliases": ["heloc", "home equity line of credit", "home equity"],
    },
    "reverse mortgage": {
        "type": "product",
        "aliases": ["reverse mortgage", "reverse", "hecm", "home equity conversion mortgage"],
    },

    # --- Metrics / requirements ---
    "loan to value": {"type": "metric", "aliases": ["ltv", "loan to value", "loan-to-value", "loan to value ratio", "ltv ratio"]},
    "combined loan to value": {
        "type": "metric",
        "aliases": ["cltv", "combined loan to value", "combined ltv"],
    },
    "debt to income": {"type": "metric", "aliases": ["dti", "debt to income", "debt-to-income", "debt to income ratio"]},
    "credit score": {"type": "metric", "aliases": ["credit score", "credit scores", "fico", "fico score", "fico scores", "credit rating"]},
    "down payment": {"type": "metric", "aliases": ["down payment", "downpayment", "down payment amount"]},
    "interest rate": {"type": "metric", "aliases": ["interest rate", "interest rates", "mortgage rate", "mortgage rates", "rate", "rates"]},
    "annual percentage rate": {"type": "metric", "aliases": ["apr", "annual percentage rate"]},
    "private mortgage insurance": {
        "type": "metric",
        "aliases": ["pmi", "private mortgage insurance", "mortgage insurance"],
    },
    "mortgage insurance premium": {"type": "metric", "aliases": ["mip", "mortgage insurance premium"]},
    "closing costs": {"type": "metric", "aliases": ["closing costs", "closing fees", "closing cost"]},
    "loan amount": {"type": "metric", "aliases": ["loan amount", "loan size", "loan amounts"]},
    "origination fee": {"type": "metric", "aliases": ["origination fee", "origination fees"]},
    "appraisal fee": {"type": "metric", "aliases": ["appraisal fee", "appraisal fees"]},

    # --- Documents ---
    "w-2": {"type": "document", "aliases": ["w2", "w-2", "w 2"]},
    "pay stub": {"type": "document", "aliases": ["pay stub", "pay stubs", "paystub", "paystubs", "pay check", "paycheck", "paychecks"]},
    "bank statement": {"type": "document", "aliases": ["bank statement", "bank statements", "bank statement pages"]},
    "tax return": {"type": "document", "aliases": ["tax return", "tax returns", "tax paperwork"]},
    "document": {"type": "document", "aliases": ["document", "documents", "documentation", "paperwork", "required documents", "form", "forms", "checklist"]},
    "1099": {"type": "document", "aliases": ["1099", "1099 form", "1099 forms", "1099s"]},
    "credit report": {"type": "document", "aliases": ["credit report", "credit reports"]},
    "loan estimate": {"type": "document", "aliases": ["loan estimate", "loan estimates"]},
    "closing disclosure": {"type": "document", "aliases": ["closing disclosure", "closing disclosures", "cd"]},
    "hud-1": {"type": "document", "aliases": ["hud 1", "hud-1", "hud1"]},
    "driver's license": {"type": "document", "aliases": ["driver license", "drivers license", "driver's license", "drivers licence", "id"]},
    "social security card": {"type": "document", "aliases": ["social security card", "ssn card", "social security number", "ssn"]},
    "green card": {"type": "document", "aliases": ["green card", "green card holder"]},
    "proof of income": {"type": "document", "aliases": ["proof of income", "income proof", "income documents"]},
    "proof of employment": {"type": "document", "aliases": ["proof of employment", "employment verification"]},
    "gift letter": {"type": "document", "aliases": ["gift letter", "gift letters"]},
    "purchase agreement": {"type": "document", "aliases": ["purchase agreement", "sales contract", "purchase contract"]},
    "pre approval letter": {"type": "document", "aliases": ["pre approval letter", "preapproval letter", "pre approval", "preapproval"]},
    "appraisal report": {"type": "document", "aliases": ["appraisal report", "appraisal"]},
    "title insurance": {"type": "document", "aliases": ["title insurance", "title commitment", "title report"]},
    "homeowners insurance": {"type": "document", "aliases": ["homeowners insurance", "home insurance", "hazard insurance", "homeowner's insurance"]},
    "flood insurance": {"type": "document", "aliases": ["flood insurance"]},
    "earnest money": {"type": "document", "aliases": ["earnest money", "earnest money deposit", "earnest"]},
    "promissory note": {"type": "document", "aliases": ["promissory note", "note", "mortgage note"]},

    # --- Property types ---
    "primary residence": {"type": "property", "aliases": ["primary residence", "primary home", "owner occupied", "owner-occupied", "owner occupied home"]},
    "second home": {"type": "property", "aliases": ["second home", "vacation home", "secondary residence", "second residence"]},
    "investment property": {"type": "property", "aliases": ["investment property", "investment properties", "investment property loan"]},
    "multi unit": {"type": "property", "aliases": ["multi unit", "multi-unit", "multifamily", "multi family", "2-4 unit", "two to four unit", "multifamily property"]},
    "condominium": {"type": "property", "aliases": ["condo", "condos", "condominium", "condominiums"]},
    "co-op": {"type": "property", "aliases": ["co op", "co-op", "coop", "cooperative"]},
    "manufactured home": {"type": "property", "aliases": ["manufactured home", "manufactured homes", "mobile home"]},

    # --- Process / status ---
    "pre approval": {"type": "process", "aliases": ["pre approval", "preapproval", "getting pre approved", "pre-qualification", "prequalification"]},
    "underwriting": {"type": "process", "aliases": ["underwriting", "underwriter", "underwriting conditions"]},
    "closing": {"type": "process", "aliases": ["closing", "closing day", "closing process", "settlement"]},
    "appraisal": {"type": "process", "aliases": ["appraisal", "home appraisal", "house appraisal"]},
    "escrow": {"type": "process", "aliases": ["escrow", "escrow account"]},
    "title search": {"type": "process", "aliases": ["title search", "title"]},
    "rate lock": {"type": "process", "aliases": ["rate lock", "rate locking", "lock rate"]},
    "occupancy": {"type": "status", "aliases": ["occupancy", "occupancy requirement", "owner occupancy", "live in", "live there", "move in", "move into", "occupy", "reside"]},
    "seasoning": {"type": "status", "aliases": ["seasoning", "seasoning requirement"]},
    "cash out": {"type": "process", "aliases": ["cash out", "cash-out", "cash out refinance"]},
    "bankruptcy": {"type": "status", "aliases": ["bankruptcy", "bankruptcies"]},
    "foreclosure": {"type": "status", "aliases": ["foreclosure", "foreclosures"]},
    "loan program": {"type": "process", "aliases": ["loan program", "loan programs", "program guidelines"]},
    "underwriting conditions": {"type": "process", "aliases": ["conditions", "loan conditions", "underwriting conditions"]},
}

# Additional common English / query words that must never be "corrected"
# into a domain term, and which join the typo-correction vocabulary.
COMMON_WORDS: set[str] = {
    "a", "about", "above", "after", "again", "all", "allowed", "also", "amount",
    "an", "and", "any", "are", "as", "at", "be", "because", "before", "between",
    "but", "by", "can", "cannot", "could", "do", "does", "during", "each", "eligible",
    "eligibility", "employment", "even", "for", "from", "get", "give", "has", "have",
    "he", "her", "his", "how", "i", "if", "in", "income", "into", "is", "it", "its",
    "just", "like", "list", "many", "may", "me", "might", "more", "most", "much",
    "must", "my", "need", "needed", "needs", "no", "not", "now", "of", "on", "one",
    "only", "or", "other", "our", "out", "over", "please", "plus", "required",
    "requires", "show", "some", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "us", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "without",
    "would", "you", "your", "minimum", "maximum", "max", "min", "limit", "limits",
     "required", "requirement", "requirements", "threshold", "document", "documents",
     "paperwork", "form", "forms", "month", "months", "year", "years", "percent",
     "percentage", "process", "steps", "step", "time", "day", "days", "checklist",
     "credit", "score", "fico", "loan", "money", "funds", "down", "payment",
     "investment", "property", "properties", "value", "home", "house",
     "lender", "borrower", "applicant", "mortgage", "refinance",
     "application", "approval", "finance", "require", "statement", "statements",
     "hello", "help", "thanks", "thank", "okay", "urgent", "asap",
     # Common conversational query words (design decision 2026-08-09).
     # These must never be "corrected" into a domain term — e.g. the valid
     # English word "borrow" must NOT become "borrower", and "owe" must not
     # become "owed" unless the user wrote it. Includes verbs, simple tenses,
     # and filler that real clients type.
     "borrow", "borrowed", "borrowing", "borrows",
     "owe", "owed", "owes", "owing",
     "pay", "pays", "paid", "paying", "payments", "payment",
     "upload", "uploads", "uploaded", "uploading",
     "submit", "submits", "submitted", "submitting",
     "send", "sends", "sent", "sending",
     "receive", "receives", "received", "receiving",
     "wait", "waits", "waiting",
     "check", "checks", "checked", "checking",
     "update", "updates", "updated", "updating",
     "happen", "happens", "happened", "happening",
     "going", "gone", "go",
     "know", "knows", "known", "knew",
     "see", "sees", "saw", "seen", "looking", "look", "looks", "looked",
     "want", "wants", "wanted",
     "soon", "status", "statuses", "status", "progress", "progressed",
     "file", "files", "filed", "docs", "docus", "documentation",
     "open", "opens", "opened", "close", "closes", "closed",
     "start", "starts", "started", "starting",
     "finish", "finishes", "finished", "finishing",
     "ready", "readied", "wrong", "issue", "issues", "problem", "problems",
     "question", "questions", "answer", "answers", "explain", "explained",
     "confirm", "confirms", "confirmed", "confirmation",
     "quote", "quotes", "quoted", "estimate", "estimates", "estimated",
     "schedule", "scheduled", "schedules", "expect", "expects", "expected",
     "today", "tomorrow", "yesterday", "week", "weeks", "today", "soon",
     "this", "that", "there", "their", "they", "them", "then", "than",
     "first", "last", "next", "any", "anyone", "anywhere", "somewhere",
     "should", "could", "would", "might", "must", "may", "can", "will",
     "do", "does", "did", "done", "doing", "have", "has", "had", "having",
     "be", "been", "being", "am", "is", "are", "was", "were", "will",
     "would", "could", "should", "might", "may", "can", "shall",
     # Ordinals / number words. "second" must NOT become "send" (it was
     # being fuzzy-corrected into the verb at ratio 80 — see the length-
     # difference guard in spell_correction._correct_token).
     "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
     "ninth", "tenth", "twelfth", "twentieth", "thirty", "forty", "fifty",
     "sixty", "seventy", "eighty", "ninety", "hundred", "hundreds",
     "thousand", "thousands", "million", "millions", "single", "married",
     "divorced", "separated", "citizen", "resident", "nonresident",
     "address", "street", "city", "state", "zip", "works", "working",
     "work", "employed", "buy", "buys", "buying", "bought", "sell",
     "sells", "selling", "sold", "own", "owns", "owning", "rent", "rents",
     "rented", "renting", "lease", "leases", "leased", "leasing", "new",
     "old", "large", "small", "high", "low", "big", "little", "both",
     "every", "few", "several", "own", "something", "anything",
     "everything", "nothing", "someone", "everyone", "everybody",
     "somebody", "nobody", "inside", "outside", "below", "above", "around",
     "behind", "beside", "toward", "whether", "though", "although",
     "maybe", "perhaps", "almost", "always", "never", "often",
     "sometimes", "usually", "again", "once", "twice", "three", "four",
     "five", "six", "seven", "eight", "nine", "ten",
     # Case-processing vocabulary. "processed" was being fuzzy-corrected
     # into "progressed" (ratio ~83, len 9->10) and "stage" into "state" —
     # both valid English words with near matches in the vocab.
     "processed", "processing", "processes", "stage", "stages", "pending",
     "approved", "approve", "approves", "approving", "review", "reviews",
     "reviewed", "reviewing", "decision", "decisions", "decide", "decides",
     "decided", "proceed", "proceeds", "proceeded", "proceeding",
     "reject", "rejects", "rejected", "rejecting", "denied", "denial",
     "accepted", "accept", "accepts", "accepting",
}

# Phrases that indicate a new question when they start a fragment.
QUESTION_STARTERS: set[str] = {
    "what", "how", "why", "when", "where", "who", "which", "whose",
    "is", "are", "do", "does", "did", "can", "could", "will", "would",
    "should", "may", "might", "must",
    "tell", "list", "show", "give", "provide", "need", "explain", "define", "describe",
    "max", "min", "maximum", "minimum",
}

# Words that are noise when a "question" fragment collapses to just them.
NOISE_WORDS: set[str] = {"help", "please", "hi", "hey", "hello", "ok", "okay", "thanks", "thank", "urgent", "asap"}

# Conjunctive/connective prefixes stripped before testing independence.
CONNECTIVE_RE = re.compile(r"^(?:and\s+)?(?:also|plus|additionally|in addition|then|or|and)\s+", re.IGNORECASE)

# Terms whose presence signals a particular intent (used by intent detection).
INTENT_KEYWORDS: dict[str, set[str]] = {
    "limits": {"max", "min", "maximum", "minimum", "limit", "limits", "threshold", "cap", "high", "low"},
    "documents": {"document", "documents", "paperwork", "forms", "form", "checklist", "what do i need"},
    "eligibility": {"eligible", "eligibility", "qualify", "qualification", "can i", "allowed"},
    "requirements": {"require", "requires", "required", "requirement", "requirements", "need", "needed", "must"},
    "process": {"process", "steps", "step", "how to", "how do", "procedure", "timeline", "how long"},
    "costs": {"rate", "rates", "cost", "costs", "fee", "fees", "apr", "pmi", "mip", "premium", "insurance", "price"},
    "definition": {"what is", "what are", "define", "meaning", "explain"},
}

# doc_type boost map for intents (used by ranking metadata boost).
INTENT_DOC_TYPE_BOOST: dict[str, set[str]] = {
    "documents": {"checklist", "form_guide"},
    "process": {"process", "program_guide"},
    "requirements": {"policy", "program_guide"},
    "limits": {"policy", "program_guide"},
}

# Alias table: every surface form -> (canonical, type). Built once.
_ALIAS_INDEX: dict[str, tuple[str, str]] = {}
for _canonical, _meta in DOMAIN_TERMS.items():
    _aliases = set(_meta["aliases"]) | {_canonical}
    for _alias in _aliases:
        _ALIAS_INDEX[_alias] = (_canonical, _meta["type"])


def aliases() -> set[str]:
    return set(_ALIAS_INDEX.keys())


def canonical_of(alias: str) -> str:
    return _ALIAS_INDEX.get(alias, alias)[0]


def type_of(alias: str) -> str | None:
    entry = _ALIAS_INDEX.get(alias)
    return entry[1] if entry else None


def multiword_aliases() -> list[str]:
    return [a for a in _ALIAS_INDEX if " " in a]
