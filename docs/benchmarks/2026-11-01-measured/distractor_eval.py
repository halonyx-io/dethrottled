import json
from pathlib import Path

from dethrottled import corpus

r = Path("/evidence")
p = json.loads((r / "multilingual-protocol.json").read_text())
h = json.loads((r / "holdout-protocol.json").read_text())
out = []
for name, c in [("minilm", corpus.Corpus()), ("dual", corpus.DualCorpus())]:
    for key, text in p["documents"]:
        c.add("https://fixture.example/" + key, "", text)
    rows = []
    for i, (expected, query, language) in enumerate(p["queries"] + h["queries"]):
        if i >= 20 and [expected, query, language] in p["queries"]:
            continue
        hits = c.search(query, limit=1)
        url = hits[0]["url"] if hits else ""
        top = (
            url.rsplit("/", 1)[-1]
            if url.startswith("https://fixture.example/")
            else "retained_distractor"
            if url
            else None
        )
        rows.append(
            {
                "query": query,
                "language": language,
                "expected": expected,
                "top_fixture": top,
                "pass": top == expected,
                "split": "calibration" if i < 20 else "holdout",
            }
        )
    out.append({"system": name, "stats": c.stats(), "rows": rows})
(r / "distractor-results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
for g in out:
    print(
        g["system"],
        {
            s: [
                sum(x["pass"] for x in g["rows"] if x["split"] == s),
                sum(x["split"] == s for x in g["rows"]),
            ]
            for s in ["calibration", "holdout"]
        },
        flush=True,
    )
