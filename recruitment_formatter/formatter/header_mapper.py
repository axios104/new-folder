"""
Maps arbitrary, jumbled source headers onto the canonical schema.

Strategy (in order), so genuinely new/unseen header phrasings still resolve
correctly without needing a code change every time:
  1. Exact match against known aliases (after normalizing whitespace/case).
  2. Exact match after stripping filler words ("of", "the", "a"...) —
     catches phrase-style headers like "Name of the Client" / "Phone No".
  3. Token-containment match: if an alias's core word(s) are fully present
     among the header's (non-filler) words, it's treated as a strong match
     even with extra words around it — e.g. "Name of Organisation" contains
     the alias "organisation", "Contact No. of Agent" contains "contact no".
     Longer/more specific aliases score higher, so more specific fields win
     ties (e.g. "agency name" beats bare "name" when both are present).
  4. Fuzzy character-similarity match (difflib) as a final catch-all for
     typos/abbreviations that don't share whole words.
  5. Unmatched -> reported to caller; column is dropped from output but
     logged so it's visible and can be turned into a permanent alias.
"""
from __future__ import annotations
import difflib
import re
from dataclasses import dataclass

from .config import SCHEMA, FUZZY_MATCH_THRESHOLD, FieldSpec

# Filler words stripped before token-based comparison. Keeps "Name of the
# Client" and "Client Name" comparable to the same core concept.
_STOPWORDS = {
    "of", "the", "a", "an", "for", "to", "in", "on", "is", "this", "that",
    "s",  # trailing possessive left after punctuation stripping ("client's")
}


def _normalize(header: str) -> str:
    if header is None:
        return ""
    h = str(header).strip().lower()
    h = re.sub(r"[_\-]+", " ", h)
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r"[^\w\s]", "", h)  # strip punctuation
    return h.strip()


def _tokens(norm: str) -> list[str]:
    return [t for t in norm.split() if t not in _STOPWORDS]


def _stripped(norm: str) -> str:
    return " ".join(_tokens(norm))


@dataclass
class MappingResult:
    # source_header -> FieldSpec.key
    matched: dict[str, str]
    # source headers we couldn't confidently map
    unmatched: list[str]
    # FieldSpec.key -> match method, for audit/logging
    method: dict[str, str]


def _build_alias_index() -> dict[str, str]:
    """normalized alias -> field key, exact-lookup table."""
    index: dict[str, str] = {}
    for field_spec in SCHEMA:
        index[_normalize(field_spec.output_name)] = field_spec.key
        for alias in field_spec.aliases:
            index[_normalize(alias)] = field_spec.key
    return index


_ALIAS_INDEX = _build_alias_index()
_ALL_NORMALIZED_ALIASES: list[tuple[str, str]] = list(_ALIAS_INDEX.items())

# Same alias set, but with filler words stripped and pre-tokenized, for the
# stopword-stripped exact match and the containment match.
_STRIPPED_ALIAS_INDEX: dict[str, str] = {
    _stripped(alias_norm): key for alias_norm, key in _ALIAS_INDEX.items()
}
_TOKENIZED_ALIASES: list[tuple[frozenset, str]] = [
    (frozenset(_tokens(alias_norm)), key)
    for alias_norm, key in _ALIAS_INDEX.items()
    if _tokens(alias_norm)
]


def _containment_score(header_tokens: set[str], alias_tokens: frozenset) -> float:
    """
    Returns a high score (0.75-0.98) if every token of alias_tokens appears
    among header_tokens (the alias's whole concept is present in the header,
    however many extra words surround it). More tokens in the alias = more
    specific = higher score, so specific aliases beat generic ones on ties.
    Returns 0.0 if the alias isn't fully contained.
    """
    if not alias_tokens or not alias_tokens.issubset(header_tokens):
        return 0.0
    return min(0.75 + 0.06 * len(alias_tokens), 0.98)


_TOKEN_TYPO_MIN_RATIO = 0.8  # per-word similarity floor for typo tolerance


def _fuzzy_containment_score(header_tokens: set[str], alias_tokens: frozenset) -> float:
    """
    Like _containment_score, but tolerates typos in individual words: each
    alias token just needs a close (>= _TOKEN_TYPO_MIN_RATIO) match among the
    header's tokens, not an exact one. Catches things like "Nam" -> "name" or
    "Phhone" -> "phone" without needing every possible misspelling as an
    alias. Scored lower than exact containment so a clean match always wins
    a tie against a typo'd one.
    """
    if not alias_tokens or not header_tokens:
        return 0.0
    ratios = []
    for atok in alias_tokens:
        best = max(
            (difflib.SequenceMatcher(None, atok, htok).ratio() for htok in header_tokens),
            default=0.0,
        )
        if best < _TOKEN_TYPO_MIN_RATIO:
            return 0.0  # every alias word must be found, even approximately
        ratios.append(best)
    avg_ratio = sum(ratios) / len(ratios)
    return min(0.70 + 0.04 * len(alias_tokens) * avg_ratio, 0.94)


def map_headers(raw_headers: list[str]) -> MappingResult:
    """
    Map a list of raw source-file headers to canonical schema keys.

    If two source headers map to the same canonical field, the first
    (left-most) column wins and the later one is reported as unmatched
    (this happens with e.g. duplicate/merged-cell artifacts).
    """
    matched: dict[str, str] = {}
    unmatched: list[str] = []
    method: dict[str, str] = {}
    used_keys: set[str] = set()

    for raw in raw_headers:
        norm = _normalize(raw)
        if not norm or norm.startswith("unnamed"):
            unmatched.append(raw)
            continue

        # 1. Exact alias match (e.g. "phone" == "phone")
        key = _ALIAS_INDEX.get(norm)
        if key and key not in used_keys:
            matched[raw] = key
            method[key] = "exact"
            used_keys.add(key)
            continue

        # 2. Exact match after stripping filler words
        #    (e.g. "Name of the Client" -> "name client")
        header_tokens_str = _stripped(norm)
        key = _STRIPPED_ALIAS_INDEX.get(header_tokens_str)
        if key and key not in used_keys:
            matched[raw] = key
            method[key] = "exact-stripped"
            used_keys.add(key)
            continue

        # 3. Token-containment match: does the header contain an alias's
        #    full set of core words, however many extra words surround it?
        #    (e.g. "Name of Organisation" contains "organisation")
        #    Tries an exact per-word match first, then a typo-tolerant
        #    per-word match (e.g. "Nam" ~ "name", "Phhone" ~ "phone").
        header_token_set = set(_tokens(norm))
        best_key, best_score, best_method = None, 0.0, ""
        if header_token_set:
            for alias_tokens, candidate_key in _TOKENIZED_ALIASES:
                if candidate_key in used_keys:
                    continue
                score = _containment_score(header_token_set, alias_tokens)
                method_label = f"contains({'+'.join(sorted(alias_tokens))})"
                if score == 0.0:
                    score = _fuzzy_containment_score(header_token_set, alias_tokens)
                    method_label = f"fuzzy-contains({'+'.join(sorted(alias_tokens))})"
                if score > best_score:
                    best_score, best_key, best_method = score, candidate_key, method_label

        # 4. Fuzzy character-similarity fallback (typos/abbreviations)
        for alias_norm, candidate_key in _ALL_NORMALIZED_ALIASES:
            if candidate_key in used_keys:
                continue
            score = difflib.SequenceMatcher(None, norm, alias_norm).ratio()
            if score > best_score:
                best_score, best_key = score, candidate_key
                best_method = f"fuzzy({score:.2f})"

        if best_key and best_score >= FUZZY_MATCH_THRESHOLD:
            matched[raw] = best_key
            method[best_key] = best_method
            used_keys.add(best_key)
        else:
            unmatched.append(raw)

    return MappingResult(matched=matched, unmatched=unmatched, method=method)
