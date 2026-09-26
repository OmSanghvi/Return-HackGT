"""Deterministic grounding check, shared by two steps of the guided tour bot:

- Build Plan step 30 (`guided_tour.validate_guided_tour`): checks that an
  `authored` fact and a step's `narration` never introduce a name, number, or
  quote that isn't already in the facts it's derived from, or in the tour's
  own vocabulary.
- Build Plan step 32 (the live guide runtime, not built yet): the same check
  runs against a model turn's spoken lines before they ever reach Unity.

No model call, no network. It never judges paraphrase quality -- it only
guarantees no new name, number, or quoted span appears, so ordinary lowercase
prose is always allowed through.
"""

from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")
_QUOTE_PAIRS = (('"', '"'), ("“", "”"))


def _tokenize(text: str | None) -> set[str]:
    return {match.group(0).lower() for match in _WORD_PATTERN.finditer(text or "")}


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for open_ch, close_ch in _QUOTE_PAIRS:
        start = 0
        while True:
            open_index = text.find(open_ch, start)
            if open_index == -1:
                break
            close_index = text.find(close_ch, open_index + 1)
            if close_index == -1:
                break
            spans.append((open_index, close_index))
            start = close_index + 1
    return spans


def _sentence_start_positions(text: str) -> set[int]:
    """Character offsets where a new sentence's first word begins."""
    starts: set[int] = set()
    first = _WORD_PATTERN.search(text)
    if first:
        starts.add(first.start())
    for boundary in re.finditer(r"[.!?]\s+", text):
        following = _WORD_PATTERN.search(text, boundary.end())
        if following:
            starts.add(following.start())
    return starts


def grounding_violations(text: str, facts: list[str], vocab: list[str]) -> list[str]:
    """Tokens in `text` that aren't licensed by `facts` or `vocab`.

    The allowed set is the lower-cased word tokens of `facts` (fact text)
    plus `vocab` (contributor display names, element labels, the theme
    title, the persona name). A token in `text` is a violation when it's a
    capitalized word that doesn't start a sentence, a token containing a
    digit, or a token inside a quoted span -- and its lower case isn't in
    the allowed set. Returns the list of violating tokens verbatim (empty
    means grounded).
    """
    allowed: set[str] = set()
    for fact_text in facts:
        allowed |= _tokenize(fact_text)
    for entry in vocab:
        allowed |= _tokenize(entry)

    text = text or ""
    sentence_starts = _sentence_start_positions(text)
    quoted_spans = _quoted_spans(text)

    violations: list[str] = []
    for match in _WORD_PATTERN.finditer(text):
        token = match.group(0)
        if token.lower() in allowed:
            continue
        is_capitalized_mid_sentence = token[:1].isupper() and match.start() not in sentence_starts
        has_digit = any(char.isdigit() for char in token)
        is_quoted = any(start <= match.start() < end for start, end in quoted_spans)
        if is_capitalized_mid_sentence or has_digit or is_quoted:
            violations.append(token)
    return violations
