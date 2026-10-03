"""Conservative lexical designation matching for primary-agent filtering."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_WORD_RE = re.compile(r"[a-z0-9]+")


def designation_confidence(actual: str, requested: str) -> float:
    """Return lexical confidence in [0, 1]; absent titles never match.

    Exact phrase or complete requested-token coverage counts as a match even
    when the site's title adds a seniority/specialty word. Partial matches use
    a conservative blend of token coverage and phrase similarity.
    """
    wanted = " ".join(_WORD_RE.findall((requested or "").lower()))
    found = " ".join(_WORD_RE.findall((actual or "").lower()))
    if not wanted or not found:
        return 0.0
    if wanted == found:
        return 1.0
    wanted_tokens = set(wanted.split())
    found_tokens = set(found.split())
    coverage = len(wanted_tokens & found_tokens) / len(wanted_tokens)
    if coverage == 1.0:
        return 1.0
    sequence = SequenceMatcher(None, wanted, found).ratio()
    return round(0.7 * coverage + 0.3 * sequence, 4)
