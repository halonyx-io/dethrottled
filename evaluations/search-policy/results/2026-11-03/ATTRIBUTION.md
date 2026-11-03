# Dataset attribution

Question text in the per-query CSV originates from the cited sources.

- HotpotQA: https://hotpotqa.github.io/ ; CC BY-SA 4.0. New questions were drawn from the public dataset via Hugging Face dataset-server rows.
- Stack Overflow: human-authored questions and accepted answers, with API-supplied author/source/licence metadata in STACK-ATTRIBUTION.json. Accepted-answer bodies are excluded from the replay pack. Question wording is reproduced; HTML/entity formatting may be normalized.
- Legacy question sources and evaluation provenance are retained in the local questions.json.

Search snippets retain their source URLs in offline-test-data.json. Relevance labels and scores are automated evaluation annotations, not statements by source authors.
