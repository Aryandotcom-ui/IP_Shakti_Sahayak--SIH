"""
person_c_generation/eval/eval_runner.py

Runs generate_answer() over test_questions.json and checks:
  1. Citation correctness — for answerable questions, the expected
     {act_name, section} pair must appear somewhere in the answer's citations.
  2. Abstention behavior — for deliberately unanswerable questions, the
     answer must come back with abstained == True.

Usage:
    python eval_runner.py            # uses MockLLM (offline, no API key needed)
    python eval_runner.py --live     # calls the real Anthropic API for every question
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PERSON_C_DIR = _THIS_DIR.parent
_REPO_ROOT = _PERSON_C_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_PERSON_C_DIR))

from shared.schema import MatchedChunk, RetrievalResult  # noqa: E402
from generate import generate_answer  # noqa: E402

TEST_QUESTIONS_PATH = _THIS_DIR / "test_questions.json"


def load_test_questions(path: Path = TEST_QUESTIONS_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_retrieval_result(q: dict) -> RetrievalResult:
    matched_chunks = [MatchedChunk.from_dict(c) for c in q["matched_chunks"]]
    return RetrievalResult(
        query=q["query"],
        matched_chunks=matched_chunks,
        confidence=q["confidence"],
        should_abstain=q["should_abstain"],
    )


def citation_matches(expected: dict, citations: list) -> bool:
    return any(
        c.act_name == expected["act_name"] and c.section == expected["section"]
        for c in citations
    )


def run_eval(mock: bool = True) -> int:
    questions = load_test_questions()
    passed = 0
    failed = 0
    failures = []

    for q in questions:
        retrieval_result = build_retrieval_result(q)
        answer = generate_answer(retrieval_result, mock=mock)

        if q["expect_abstain"]:
            ok = answer.abstained is True
            reason = "" if ok else f"expected abstain=True, got {answer.abstained}"
        else:
            ok = (not answer.abstained) and citation_matches(q["expected_citation"], answer.citations)
            if not ok:
                if answer.abstained:
                    reason = "model abstained but question was expected to be answerable"
                else:
                    got = [(c.act_name, c.section) for c in answer.citations]
                    reason = f"expected citation {q['expected_citation']} not found in {got}"
            else:
                reason = ""

        if ok:
            passed += 1
            print(f"[PASS] {q['id']}: {q['query'][:60]}")
        else:
            failed += 1
            failures.append((q["id"], reason))
            print(f"[FAIL] {q['id']}: {q['query'][:60]}  -- {reason}")

    total = passed + failed
    print("\n" + "-" * 60)
    print(f"{passed}/{total} passed")
    if failures:
        print("\nFailures:")
        for qid, reason in failures:
            print(f"  - {qid}: {reason}")

    return 0 if failed == 0 else 1


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Run the citation/abstention eval suite.")
    parser.add_argument(
        "--live", action="store_true",
        help="Call the real Anthropic API instead of MockLLM (requires ANTHROPIC_API_KEY).",
    )
    args = parser.parse_args(argv)

    exit_code = run_eval(mock=not args.live)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
