"""Native-weight token admission gates; no downloads or weight changes."""

import pytest

from dethrottled.corpus import MODELS
from dethrottled.corpus_chunks import chunks
from dethrottled.corpus_v2 import CorpusV2
from dethrottled.evidence import Documents

available = all(
    (MODELS / directory / name).is_file()
    for directory in ("emb-minilm", "emb-e5")
    for name in ("model.onnx", "tokenizer.json")
)


@pytest.mark.skipif(not available, reason="both existing model assets required")
def test_token_admission_for_unicode_and_long_identifiers(tmp_path):
    from dethrottled.corpus import _model, embed

    obj = CorpusV2(
        tmp_path / "tokens.sqlite",
        documents=Documents(tmp_path / "docs.sqlite"),
        models=["minilm", "e5-test"],
    )
    models = [_model("minilm"), _model("e5")]
    settings = [(dict(model["tok"].truncation), dict(model["tok"].padding)) for model in models]
    text = (
        "日本語の技術資料を読む。" * 150
        + "\n\n"
        + "بيانات الصيانة باللغة العربية. " * 100
        + "\n\n"
        + "LONG_IDENTIFIER_" * 150
    )
    result = obj._token_chunks(list(chunks(text)))
    assert "".join(item.text for item in result) == text
    assert all(
        not model["tok"].encode(prefix + item.text).overflowing
        for model, prefix in zip(models, ("", "passage: "))
        for item in result
    )
    assert settings == [
        (dict(model["tok"].truncation), dict(model["tok"].padding)) for model in models
    ]
    for model in ("minilm", "e5"):
        vectors = embed([result[0].text], model_name=model)
        assert len(vectors[0]) == 384
        assert sum(value * value for value in vectors[0]) == pytest.approx(1, abs=1e-5)
