"""Query normalization.

Deterministic, dependency-free cleaning that makes raw user input
comparable. Deliberately conservative: numbers, percentages, dollar
amounts, acronyms and domain terms are preserved untouched.

The goal is *not* to rewrite the user's question — it is to remove
noise (case, spacing, punctuation, contractions) so that spelling
correction, splitting and search all see a clean, canonical form.
"""

from __future__ import annotations

import re
import unicodedata

CONTRACTIONS: dict[str, str] = {
    "whats": "what is", "what's": "what is", "whatre": "what are", "what're": "what are",
    "what've": "what have", "whos": "who is", "who's": "who is", "who're": "who are",
    "hows": "how is", "how's": "how is", "whys": "why is", "why's": "why is",
    "whens": "when is", "when's": "when is", "wheres": "where is", "where's": "where is",
    "its": "it is", "it's": "it is", "thats": "that is", "that's": "that is",
    "theres": "there is", "there's": "there is", "theres": "there is",
    "dont": "do not", "don't": "do not", "doesnt": "does not", "doesn't": "does not",
    "cant": "cannot", "can't": "cannot", "couldnt": "could not", "couldn't": "could not",
    "wouldnt": "would not", "wouldn't": "would not", "shouldnt": "should not", "shouldn't": "should not",
    "wont": "will not", "won't": "will not", "isnt": "is not", "isn't": "is not",
    "arent": "are not", "aren't": "are not", "wasnt": "was not", "wasn't": "was not",
    "werent": "were not", "weren't": "were not", "mustnt": "must not", "mustn't": "must not",
    "im": "i am", "i'm": "i am", "ive": "i have", "i've": "i have",
    "youre": "you are", "you're": "you are", "youve": "you have", "you've": "you have",
    "we're": "we are", "theyre": "they are", "they're": "they are",
    "lets": "let us", "let's": "let us", "gonna": "going to", "wanna": "want to",
    "gotta": "got to", "kinda": "kind of", "lemme": "let me", "gimme": "give me",
    "whatis": "what is", "whats": "what is",
}

# Applied to sub-query text for search (after splitting). Keeps letters,
# digits, %, $, ., - and internal apostrophes; drops the rest.
_STRIP_FOR_SEARCH_RE = re.compile(r"[^\w\s%$.\-']+")


def normalize(raw: str) -> str:
    """Return a clean, canonical lowercased string, keeping sentence
    markers (``? ! ; ,``) and numbers intact."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", raw)
    # curly/typographic apostrophes -> straight
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.lower()
    # expand known contractions (match word boundaries to avoid clobbering)
    for src, dst in CONTRACTIONS.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    # collapse all whitespace runs to single spaces
    text = re.sub(r"\s+", " ", text)
    # collapse repeated punctuation marks
    text = re.sub(r"\?{2,}", "?", text)
    text = re.sub(r"!{2,}", "!", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r",{2,}", ",", text)
    # collapse immediately repeated words ("what what is" -> "what is")
    text = re.sub(r"\b(\w+)(\s+\1\b)+", r"\1", text)
    # normalize spacing around punctuation
    text = re.sub(r"\s+([?!.,;])", r"\1", text)
    text = re.sub(r"([?!.,;])(\w)", r"\1 \2", text)
    return text.strip()


def clean_for_search(text: str) -> str:
    """Strip non-essential punctuation from an already-normalized string.

    Keeps letters, digits, ``%``, ``$``, ``.`` and ``-`` so financial
    values like ``30%`` or ``$100,000`` survive. Removes question marks,
    commas, semicolons, etc.
    """
    cleaned = _STRIP_FOR_SEARCH_RE.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def is_empty(text: str) -> bool:
    return not text.strip()


def has_numeric_content(text: str) -> bool:
    return bool(re.search(r"\d", text))
