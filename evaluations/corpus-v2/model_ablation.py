#!/usr/bin/env python3
"""Compare existing retrievers on a fresh, offline cross-language challenge.

Use an empty DETHROTTLED_DATA_DIR and the existing pinned model assets.
No training, model downloads, external requests or production writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from pathlib import Path


def manifest():
    cases = [
        (
            "ja",
            "冷凍保管庫の保守",
            "停電時には冷凍保管庫の扉を閉めたままにしてください。",
            "During a power outage, what should happen to the freezer door?",
        ),
        (
            "ar",
            "صيانة المضخة",
            "يجب استبدال حشية المضخة كل تسعين يوماً.",
            "How frequently must the pump gasket be replaced?",
        ),
        (
            "zh",
            "温室灌溉",
            "温室灌溉系统只在日出前运行。",
            "At what time of day does the greenhouse irrigation operate?",
        ),
        (
            "ru",
            "Техническое обслуживание лифта",
            "Перед осмотром лифта необходимо отключить главный выключатель.",
            "What must be switched off before inspecting the elevator?",
        ),
        (
            "ko",
            "배터리 보관",
            "배터리는 직사광선을 피해 건조한 곳에 보관해야 합니다.",
            "Where should batteries be stored to protect them from sunlight and moisture?",
        ),
        (
            "th",
            "การดูแลเครื่องกรองน้ำ",
            "ควรเปลี่ยนไส้กรองน้ำทุกหกเดือน",
            "How often should the water filter cartridge be replaced?",
        ),
        (
            "fr",
            "Entretien du compresseur",
            "La soupape du compresseur doit être remplacée après 730 heures de fonctionnement.",
            "When must the compressor valve be replaced?",
        ),
        (
            "es",
            "Control del horno",
            "La temperatura máxima de seguridad del horno es de 285 grados Celsius.",
            "What is the maximum safe oven temperature?",
        ),
        (
            "de",
            "Wartung der Wasserpumpe",
            "Der Filter der Wasserpumpe muss alle 46 Tage gereinigt werden.",
            "How often should the water pump filter be cleaned?",
        ),
        (
            "ms",
            "Pemeriksaan pam",
            "Injap keselamatan mesti diperiksa sebelum pam dihidupkan.",
            "What must be inspected before starting the pump?",
        ),
        (
            "en",
            "Emergency chamber purge",
            "The emergency chamber is purged with argon before the lid opens.",
            "Which gas clears the emergency enclosure before opening?",
        ),
        (
            "en-2",
            "Dispatch ledger retention",
            "The dispatch ledger must retain the original customs declaration.",
            "Which original border document needs to be kept in the shipping register?",
        ),
    ]
    docs, questions = [], []
    for language, title, fact, query in cases:
        url = "https://example.org/ablation/" + language
        docs.append(dict(url=url, title=title, text=fact))
        questions.append(dict(id=language + "-cross-language", query=query, url=url, facts=[fact]))
        if not language.startswith("en"):
            questions.append(
                dict(id=language + "-same-language", query=title, url=url, facts=[fact])
            )
    for index, query in enumerate(
        [
            "How do black holes emit Hawking radiation?",
            "What medications treat seasonal allergic rhinitis?",
            "Who won the Nobel Prize for literature in 1954?",
            "How do emperor penguins incubate their eggs?",
            "Which treaty ended the Thirty Years War?",
            "How do I bake a sourdough loaf?",
            "What is the capital city of Mongolia?",
            "How does a violin produce sound?",
            "Which programming languages compile to WebAssembly?",
            "How is a kidney transplant performed?",
            "What causes the northern lights?",
            "How are parliamentary elections counted?",
            "How can a chess player castle queenside?",
            "Why do leaves change colour in autumn?",
            "What did the Rosetta spacecraft discover?",
            "How are diamonds formed underground?",
            "What is the speed of light in a vacuum?",
            "How does public key cryptography work?",
            "What are the rules of cricket?",
            "Who painted The Starry Night?",
            "ブラックホールはどのように蒸発しますか？",  # noqa: RUF001 — natural punctuation
            "ما هي عاصمة منغوليا؟",
            "谁画了星夜？",  # noqa: RUF001 — natural punctuation
            "Почему листья меняют цвет осенью?",
        ]
    ):
        questions.append(dict(id="negative-%d" % index, query=query, url=None, facts=[]))
    return dict(documents=docs, questions=questions)


def validation_questions(data):
    """Additional queries frozen after support-policy development; same documents."""
    by_language = {doc["url"].rsplit("/", 1)[-1]: doc for doc in data["documents"]}
    questions = []
    for language, query in [
        ("en", "What substance is used to flush the emergency chamber?"),
        ("en-2", "What paperwork must remain in the dispatch ledger?"),
        ("ru", "Before checking the lift, which electrical control must be disconnected?"),
        ("ko", "What storage conditions keep the batteries safe?"),
        ("zh", "温室灌溉"),
        ("ja", "冷凍保管庫の保守"),
        ("fr", "Après combien d'heures faut-il remplacer la soupape du compresseur?"),
        ("ar", "صيانة المضخة"),
    ]:
        doc = by_language[language]
        questions.append(
            dict(id="validation-" + language, query=query, url=doc["url"], facts=[doc["text"]])
        )
    for index, query in enumerate(
        [
            "What makes tectonic plates move?",
            "Which planet has the most moons?",
            "How many strings does a standard guitar have?",
            "What is the difference between a sonnet and a haiku?",
            "When did the Qing dynasty end?",
            "Why do distant galaxies appear redshifted?",
            "Which bacteria cause Lyme disease?",
            "What is the binomial theorem?",
            "日本の首都はどこですか?",
            "كم عدد أوتار الغيتار؟",
            "什么是光合作用?",
            "Кто написал роман Война и мир?",
        ]
    ):
        questions.append(dict(id="validation-negative-%d" % index, query=query, url=None, facts=[]))
    return questions


def run(output, validation=False, reuse=False):
    os.environ["DETHROTTLED_MULTILINGUAL_CORPUS"] = "1"
    from dethrottled.corpus_v2 import CorpusV2

    store = CorpusV2()
    if store.status()["active_sources"] and not reuse:
        raise RuntimeError("Use an empty isolated data directory")
    data = manifest()
    if validation:
        data["questions"] = validation_questions(data)
    if reuse:
        urls = {r[0] for r in store.db.execute("SELECT url FROM sources WHERE active=1")}
        if urls != {d["url"] for d in data["documents"]}:
            raise RuntimeError("Replay requires exactly the isolated synthetic fixture corpus")
    for doc in data["documents"]:
        result = store.enqueue(
            doc["url"], doc["title"], doc["text"], {"corpus_visibility": "public"}
        )
        assert result["accepted"]
        if reuse:
            assert result["unchanged"], "fixture content changed; use a fresh capture"
        else:
            assert store.run_one()
    both = list(store.models)
    results = []
    for name, models, support in [
        ("both", both, "standard"),
        ("both-broad", both, "broad"),
        ("minilm", ["minilm"], "standard"),
        ("minilm-broad", ["minilm"], "broad"),
        ("e5", [m for m in both if m != "minilm"], "standard"),
        ("e5-broad", [m for m in both if m != "minilm"], "broad"),
    ]:
        store.models = models
        rows = []
        for repeat in range(3):
            for question in data["questions"]:
                start = time.perf_counter()
                hits = store.search(question["query"], mode="semantic", support=support)
                elapsed = (time.perf_counter() - start) * 1000
                ranks = [
                    rank
                    for rank, hit in enumerate(hits, 1)
                    if question["facts"]
                    and hit["url"] == question["url"]
                    and all(f.casefold() in hit["text"].casefold() for f in question["facts"])
                ]
                rows.append(
                    dict(
                        id=question["id"],
                        repeat=repeat,
                        answer_rank=min(ranks) if ranks else None,
                        negative=not question["facts"],
                        elapsed_ms=elapsed,
                        hits=hits,
                    )
                )
        positives = [r for r in rows if not r["negative"]]
        negatives = [r for r in rows if r["negative"]]
        warm = [r["elapsed_ms"] for r in rows if r["repeat"] > 0]
        summary = dict(
            models=name,
            support=support,
            positive_questions=len(positives) // 3,
            recall_at_5=sum(bool(r["answer_rank"] and r["answer_rank"] <= 5) for r in positives)
            / len(positives),
            negative_questions_with_hits=len({r["id"] for r in negatives if r["hits"]}),
            negative_questions=len(negatives) // 3,
            warm_median_ms=statistics.median(warm),
        )
        print(json.dumps(summary), flush=True)
        results.append(dict(summary=summary, queries=rows))
    Path(output).write_text(
        json.dumps(
            dict(
                manifest=data,
                dataset="validation" if validation else "cross-language-development",
                manifest_sha256=hashlib.sha256(
                    json.dumps(data, sort_keys=True).encode()
                ).hexdigest(),
                results=results,
            ),
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--validation", action="store_true")
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    run(args.output, args.validation, args.reuse)
