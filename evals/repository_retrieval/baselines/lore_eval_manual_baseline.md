# Lore Retrieval Eval — Manual Baseline

Dataset: `evals/repository_retrieval/lore_eval.json`

Manual eval was not run in this environment because it requires:
- a running API server (`uvicorn` / Docker)
- an already imported and synced Lore repository
- a known repository UUID

## How to run

```bash
python scripts/eval_repository_retrieval.py \
  --base-url http://localhost:8000/api/v1 \
  --repository-id <REPOSITORY_UUID> \
  --dataset evals/repository_retrieval/lore_eval.json
```

## What changed in PR #12

- `tokenize_query` now filters generic English stopwords (`how`, `does`, `the`, `what`, etc.).
  Domain/code terms (`repository`, `sync`, `service`, etc.) are preserved.
- `score_document` now gives basename/filename term hits a stronger weight (`+6.0`) than
  directory-only path hits (`+4.0`), making filename matches rank higher than directory matches.

## Notes

This file is manual/dev only. It is not part of CI and eval results are not persisted.
