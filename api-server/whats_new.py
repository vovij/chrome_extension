"""
Extract "what's new" in the current article compared to reference articles.
Used to highlight new entities and numbers when novelty score is low (mostly repeated content).
"""
import re
from typing import List, Dict, Optional

# Common words to skip when extracting "entities" (capitalized phrases)
STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "was", "are", "were", "been", "be", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "must", "can", "this", "that", "these", "those", "it", "its"
})


def _normalize_for_compare(text: str) -> str:
    """Lowercase and normalize whitespace for comparison."""
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def extract_numbers(text: str) -> List[str]:
    """
    Extract notable numbers from text: percentages, currency, large numbers with K/M/B.
    Returns unique strings as they appear (e.g. "15%", "$2.5 billion").
    """
    if not text:
        return []
    seen = set()
    out = []
    # Percentages: 15%, 3.2%
    for m in re.finditer(r"\d+\.?\d*\s*%", text):
        s = m.group().strip()
        if s not in seen and len(s) <= 15:
            seen.add(s)
            out.append(s)
    # Currency: $1.2M, €500, £10 billion
    for m in re.finditer(r"[€$£]\s*\d+(?:[.,]\d+)*(?:\s*(?:million|billion|trillion|M|B|K))?", text, re.I):
        s = m.group().strip()
        if s not in seen and len(s) <= 25:
            seen.add(s)
            out.append(s)
    # Large numbers: 1,234,567 or 1.2 million
    for m in re.finditer(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:million|billion|trillion|thousand)", text, re.I):
        s = m.group().strip()
        if s not in seen and len(s) <= 25:
            seen.add(s)
            out.append(s)
    return out[:10]  # cap at 10


def extract_entities(text: str) -> List[str]:
    """
    Extract likely named entities: consecutive capitalized words (Title Case).
    Skips common words. Returns up to 10 unique phrases.
    """
    if not text:
        return []
    # Match 2–4 consecutive words that start with uppercase
    pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
    seen = set()
    out = []
    for m in re.finditer(pattern, text):
        phrase = m.group(1).strip()
        # Skip if any word is a stopword
        words = phrase.split()
        if any(w.lower() in STOPWORDS for w in words):
            continue
        # Skip very short or generic
        if len(phrase) < 4 or phrase in seen:
            continue
        seen.add(phrase)
        out.append(phrase)
        if len(out) >= 10:
            break
    return out


def _split_sentences(text: str) -> List[str]:
    """
    Split text into sentences on sentence-ending punctuation.
    """
    if not text or not text.strip():
        return []
    text = re.sub(r"\s+", " ", text.strip())
    # Split on . ! ? followed by space
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 1]


LINK_WORDS = frozenset(
    {
        "and",
        "or",
        "vs",
        "vs.",
        "&",
        "-",
        "|",
        "/",
        "the",
        "a",
        "an",
    }
)


def _sentence_is_only_entities(sentence: str, entities: List[str]) -> bool:
    """
    Heuristic: detect sentences that are essentially just a list of entity
    titles (e.g. related-article headlines) with no other meaningful words.
    """
    if not sentence or not entities:
        return False

    tmp = sentence
    for e in entities:
        if not e:
            continue
        tmp = re.sub(re.escape(e), " ", tmp, flags=re.IGNORECASE)

    # Strip punctuation and split into tokens
    tmp = re.sub(r"[^\w\s]", " ", tmp)
    tokens = [t.lower() for t in tmp.split() if t.strip()]

    # Remove link / glue words and purely numeric tokens
    remaining = [
        t for t in tokens if t not in LINK_WORDS and not t.isdigit()
    ]

    # If nothing remains, the sentence was basically just entity names
    return len(remaining) == 0


def _select_candidate_sentences(
    text: str,
    new_entities: List[str],
    new_numbers: List[str],
    max_sentences: int = 5,
) -> List[str]:
    """
    Pick the longest sentences that carry the most 'new' entities/numbers,
    while skipping sentences that are basically just lists of entity titles.
    """
    sentences = _split_sentences(text)
    candidates = []

    for idx, s in enumerate(sentences):
        s_norm = _normalize_for_compare(s)
        if not s_norm:
            continue

        ents_in_s = [
            e for e in new_entities if e and e.lower() in s_norm
        ]
        nums_in_s = [
            n for n in new_numbers if n and n.lower() in s_norm
        ]

        total_new = len(set(ents_in_s)) + len(set(nums_in_s))
        if total_new == 0:
            continue

        # Skip sentences that are effectively just entity lists
        if _sentence_is_only_entities(s, ents_in_s):
            continue

        candidates.append(
            (
                idx,
                s,
                len(set(ents_in_s)),   # how many distinct entities
                len(set(nums_in_s)),   # how many distinct numbers
                len(s),                # length as tie-breaker
            )
        )

    if not candidates:
        return []

    # Rank: more entities -> more numbers -> longer sentence
    candidates.sort(key=lambda t: (-t[2], -t[3], -t[4]))
    top = candidates[:max_sentences]

    # Preserve original order for readability
    top_sorted = sorted(top, key=lambda t: t[0])
    return [s for _, s, _, _, _ in top_sorted]


def compute_whats_new(
    current_title: str,
    current_content: str,
    reference_contents: Dict[str, tuple],
) -> Dict:
    """
    Compare current article to reference articles and return entities/numbers
    that appear in current but not in any reference, plus a summary paragraph
    built from sentences containing those items.
    """
    combined_ref = " ".join(
        (t or "") + " " + (c or "")
        for t, c in reference_contents.values()
    )
    ref_normalized = _normalize_for_compare(combined_ref)

    current_text = (current_title or "") + " " + (current_content or "")

    new_entities = []
    for e in extract_entities(current_text):
        if _normalize_for_compare(e) not in ref_normalized:
            new_entities.append(e)

    new_numbers = []
    for n in extract_numbers(current_text):
        if n.lower() not in ref_normalized:
            new_numbers.append(n)

    # Build candidate sentences and summary from them
    summary_sentences = _select_candidate_sentences(
        current_text,
        new_entities[:5],
        new_numbers[:5],
        max_sentences=5,
    )
    summary = ""
    if summary_sentences:
        summary = " ".join(summary_sentences)
        # Truncate if very long (banner has limited space)
        if len(summary) > 400:
            summary = summary[:397] + "..."

    return {
        "new_entities": new_entities[:5],
        "new_numbers": new_numbers[:5],
        "sentences": summary_sentences,
        "summary": summary,
    }
