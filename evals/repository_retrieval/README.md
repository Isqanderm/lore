# Repository Retrieval Evaluation

Manual/dev evaluation harness for the Lore `/search` and `/context` endpoints.

## Prerequisites

- API server is running (e.g. `make run` or `uvicorn apps.api.main:app`)
- A repository has already been imported and synced
- The repository's UUID is known

This is a **manual dev tool**. It is NOT CI-blocking.

## Usage

Run from the repository root:

```bash
python scripts/eval_repository_retrieval.py \
  --base-url http://localhost:8000/api/v1 \
  --repository-id <REPOSITORY_UUID> \
  --dataset evals/repository_retrieval/lore_eval.json
```

## Options

| Flag | Default | Description |
|---|---|---|
| `--base-url` | required | API base URL |
| `--repository-id` | required | Repository UUID |
| `--dataset` | required | Path to eval dataset JSON |
| `--search-limit` | 10 | Search results to request (1–50) |
| `--context-limit` | 8 | Context sources to request (1–20) |
| `--max-chars` | 12000 | Max total characters in context (1000–50000) |
| `--excerpt-chars` | 2000 | Max characters per excerpt (300–10000) |
| `--min-top3` | 0.70 | Minimum search_top3_path_hit ratio to pass (0–1) |
| `--min-context-hit` | 0.70 | Minimum context_path_hit ratio to pass (0–1) |

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Eval completed, thresholds passed |
| 1 | Eval completed, quality below threshold |
| 2 | Config/arg validation, dataset parsing, or API/network error |
