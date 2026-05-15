#!/usr/bin/env python3
"""Repository retrieval evaluation CLI.

Run against an already-running API with an already-imported and synced repository.

Example (run from repository root):
    python scripts/eval_repository_retrieval.py \\
        --base-url http://localhost:8000/api/v1 \\
        --repository-id 00000000-0000-0000-0000-000000000000 \\
        --dataset evals/repository_retrieval/lore_eval.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Allow direct execution from the repository root:
#   python scripts/eval_repository_retrieval.py ...
# Without this, evals/ would not be on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from evals.repository_retrieval.eval_logic import (  # noqa: E402
    evaluate_case,
    extract_context_sources,
    extract_search_paths,
    format_report,
    load_dataset,
    summarize_results,
    thresholds_passed,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repository retrieval quality evaluation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="API base URL, e.g. http://localhost:8000/api/v1",
    )
    parser.add_argument("--repository-id", required=True, help="Repository UUID")
    parser.add_argument("--dataset", required=True, help="Path to eval dataset JSON")
    parser.add_argument("--search-limit", type=int, default=10)
    parser.add_argument("--context-limit", type=int, default=8)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--excerpt-chars", type=int, default=2000)
    parser.add_argument("--min-top3", type=float, default=0.70)
    parser.add_argument("--min-context-hit", type=float, default=0.70)
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> str | None:
    """Return an error message if args are invalid, else None."""
    if not 0.0 <= args.min_top3 <= 1.0:
        return "--min-top3 must be between 0.0 and 1.0"
    if not 0.0 <= args.min_context_hit <= 1.0:
        return "--min-context-hit must be between 0.0 and 1.0"
    if not 1 <= args.search_limit <= 50:
        return "--search-limit must be between 1 and 50"
    if not 1 <= args.context_limit <= 20:
        return "--context-limit must be between 1 and 20"
    if not 1000 <= args.max_chars <= 50000:
        return "--max-chars must be between 1000 and 50000"
    if not 300 <= args.excerpt_chars <= 10000:
        return "--excerpt-chars must be between 300 and 10000"
    if args.excerpt_chars > args.max_chars:
        return "--excerpt-chars must be <= --max-chars"
    return None


def call_search(
    client: httpx.Client,
    base_url: str,
    repository_id: str,
    query: str,
    limit: int,
) -> dict[str, Any]:
    url = f"{base_url}/repositories/{repository_id}/search"
    response = client.post(url, json={"query": query, "limit": limit})
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def call_context(
    client: httpx.Client,
    base_url: str,
    repository_id: str,
    query: str,
    limit: int,
    max_chars: int,
    excerpt_chars: int,
) -> dict[str, Any]:
    url = f"{base_url}/repositories/{repository_id}/context"
    response = client.post(
        url,
        json={
            "query": query,
            "limit": limit,
            "max_chars": max_chars,
            "excerpt_chars": excerpt_chars,
        },
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def main() -> int:
    args = parse_args()

    validation_error = _validate_args(args)
    if validation_error:
        print(f"Error: {validation_error}", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")

    try:
        dataset = load_dataset(args.dataset)
    except Exception as exc:
        print(f"Error loading dataset: {exc}", file=sys.stderr)
        return 2

    results = []
    with httpx.Client(timeout=30.0) as client:
        for case in dataset.cases:
            try:
                search_response = call_search(
                    client,
                    base_url,
                    args.repository_id,
                    case.query,
                    args.search_limit,
                )
                search_paths = extract_search_paths(search_response)
            except (
                httpx.TimeoutException,
                httpx.HTTPStatusError,
                httpx.RequestError,
                ValueError,
            ) as exc:
                print(f"Error in case '{case.id}' (search): {exc}", file=sys.stderr)
                return 2

            try:
                context_response = call_context(
                    client,
                    base_url,
                    args.repository_id,
                    case.query,
                    args.context_limit,
                    args.max_chars,
                    args.excerpt_chars,
                )
                context_sources = extract_context_sources(context_response)
            except (
                httpx.TimeoutException,
                httpx.HTTPStatusError,
                httpx.RequestError,
                ValueError,
            ) as exc:
                print(f"Error in case '{case.id}' (context): {exc}", file=sys.stderr)
                return 2

            results.append(evaluate_case(case, search_paths, context_sources))

    summary = summarize_results(results)
    report = format_report(dataset, results, summary, args.min_top3, args.min_context_hit)
    print(report)

    return 0 if thresholds_passed(summary, args.min_top3, args.min_context_hit) else 1


if __name__ == "__main__":
    raise SystemExit(main())
