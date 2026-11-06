"""Cheap, explicit retrieval corroboration, separate from answer verification."""

from __future__ import annotations

import re
import unicodedata

# Question scaffolding must not corroborate an otherwise unrelated passage.
_STOP = frozenset(
    "a an and are as at be been before by can could did do does for from had has have "
    "how i in is it its me must of on or should that the their them there these they "
    "this to was were what when where which who why will with would you your".split()
)


def terms(text):
    return {word for word in re.findall(r"\w+", text.casefold()) if word not in _STOP}


def query_anchors(query, row):
    """Bounded literal overlap diagnostics; absence can also mean paraphrase.

    These describe the returned passage/title, never the whole corpus or
    whether a fact is supported. They do not participate in ranking/filtering.
    """
    words = terms(query)
    matched = words & terms(row["title"] + " " + row["text"])
    missing = words - matched
    return {"scope": "returned_passage_and_title", "matched_count": len(matched),
            "unmatched_count": len(missing),
            "matched_terms": [word[:64] for word in sorted(matched)[:12]],
            "unmatched_terms": [word[:64] for word in sorted(missing)[:12]],
            "interpretation": "literal_overlap_only; paraphrases_may_not_share_terms"}


def assess(query, row, models):
    """Require model/source agreement or meaningful literal anchors.

    Agreement is at source level so different passage choices do not discard
    an answer. This does not establish entailment, factual accuracy, or even
    answer presence. Broad retrieval keeps unconfirmed candidates separately
    identifiable, including cross-language single-model matches.
    """
    models = set(models)
    # The installed MiniLM is an English retriever, not a multilingual model.
    # Its unsupported-script similarities must not corroborate E5. This is a
    # script applicability check, not guessed language identification.
    letters = [c for c in query if c.isalpha()]
    if letters and sum("LATIN" not in unicodedata.name(c, "") for c in letters) > len(letters) / 2:
        models.discard("minilm")
    if "lexical" in models:
        return "lexical_match"
    if len(models) >= 2:
        return "model_agreement"
    words = terms(query)
    anchors = words & terms(row["title"] + " " + row["text"])
    if words and len(anchors) >= min(2, len(words)):
        return "query_terms"
    return "unconfirmed"
