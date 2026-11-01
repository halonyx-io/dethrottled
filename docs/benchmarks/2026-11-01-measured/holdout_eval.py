# ruff: noqa: RUF001
import json
from pathlib import Path

from dethrottled import corpus

r = Path("/evidence")
p = json.loads((r / "multilingual-protocol.json").read_text())
holdout = [
    ["shipping", "港口运出了多少箱机器零件？", "zh"],
    ["museum", "成人参观历史博物馆要付多少欧元？", "zh"],
    ["penguin", "企鹅在什么地方的冰上繁殖？", "zh"],
    ["library", "图书馆星期六几点关门？", "zh"],
    ["water", "Berapakah kandungan arsenik dalam bekalan air minuman?", "ms"],
    ["solar", "Berapakah kapasiti penjanaan tenaga suria yang dipasang?", "ms"],
    ["shipping", "Berapakah jumlah peti komponen mesin dalam penghantaran itu?", "ms"],
    ["museum", "Berapakah harga tiket dewasa untuk masuk muzium?", "ms"],
    ["rail", "À quelle heure part le dernier train vers le nord ?", "fr"],
    ["solar", "Quelle est la puissance solaire installée en mégawatts ?", "fr"],
    ["hospital", "Combien de lits compte le nouveau service pour enfants ?", "fr"],
    ["water", "Quelle concentration d'arsenic a été mesurée dans l'eau potable ?", "fr"],
]
negative = [
    "What is the capital city of Peru?",
    "火星表面温度是多少？",
    "Apakah nombor telefon kedutaan?",
    "Quelle est la recette du gâteau au chocolat ?",
]
# Save the protocol before evaluating; no threshold changes after this point.
(r / "holdout-protocol.json").write_text(
    json.dumps({"queries": holdout, "negative": negative}, ensure_ascii=False, indent=2)
)
results = []
for name, c in [("minilm", corpus.Corpus()), ("dual", corpus.DualCorpus())]:
    for key, text in p["documents"]:
        c.add("https://fixture.example/" + key, "", text)
    rows = []
    for expected, q, lang in p["queries"] + holdout:
        hits = c.search(q, limit=1)
        top = hits[0]["url"].rsplit("/", 1)[-1] if hits else None
        rows.append(
            {
                "query": q,
                "language": lang,
                "expected": expected,
                "top": top,
                "pass": top == expected,
                "split": "calibration"
                if len(rows) < 20
                else ("duplicate_excluded" if [expected, q, lang] in p["queries"] else "holdout"),
            }
        )
    for q in p["negative"] + negative:
        hits = c.search(q, limit=1)
        rows.append(
            {
                "query": q,
                "expected": None,
                "top": hits[0]["url"] if hits else None,
                "pass": not hits,
                "split": "negative_calibration" if q in p["negative"] else "negative_holdout",
            }
        )
    results.append({"system": name, "rows": rows})
(r / "holdout-results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
for group in results:
    print(
        group["system"],
        {
            s: [
                sum(x["pass"] for x in group["rows"] if x["split"] == s),
                sum(x["split"] == s for x in group["rows"]),
            ]
            for s in ["calibration", "holdout", "negative_calibration", "negative_holdout"]
        },
        flush=True,
    )
