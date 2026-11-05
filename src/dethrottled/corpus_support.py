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
