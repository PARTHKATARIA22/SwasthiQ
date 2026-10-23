#!/usr/bin/env python3
"""
Grading script for the SwasthiQ Clinic Front Desk Agent.

Compares results/*.json (produced by runner.py) against the expected blocks
in conversations/*.json.

Checks:
  - terminal_state matches expected
  - escalation_reason matches expected (null or specific reason)
  - must_call: every listed tool name appears in tool_calls
  - must_not_call: no listed tool name appears in tool_calls

Usage:
    python grade.py
    python grade.py --results results/ --conversations conversations/
    python grade.py --verbose
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


def load_conversations(conv_dir: pathlib.Path) -> dict[str, dict]:
    """Load all conversation scripts keyed by their id."""
    conversations = {}
    for path in sorted(conv_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            conv = json.load(f)
        conversations[conv["id"]] = conv
    return conversations


def load_results(results_dir: pathlib.Path) -> dict[str, list[dict]]:
    """Load all result files, grouped by conversation_id.
    Each conversation may have multiple runs (e.g. cv_0001.run1.json, cv_0001.run2.json)."""
    results: dict[str, list[dict]] = {}
    for path in sorted(results_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            result = json.load(f)
        cid = result.get("conversation_id", path.stem.split(".")[0])
        results.setdefault(cid, []).append(result)
    return results


def grade_single(result: dict, expected: dict, verbose: bool = False) -> dict[str, Any]:
    """Grade a single result against expected. Returns a dict of check results."""
    checks = {}
    tool_names_called = {call["name"] for call in result.get("tool_calls", [])}

    # 1. terminal_state
    expected_state = expected.get("terminal_state")
    actual_state = result.get("terminal_state")
    checks["terminal_state"] = {
        "pass": actual_state == expected_state,
        "expected": expected_state,
        "actual": actual_state,
    }

    # 2. escalation_reason
    expected_reason = expected.get("escalation_reason")
    actual_reason = result.get("escalation_reason")
    checks["escalation_reason"] = {
        "pass": actual_reason == expected_reason,
        "expected": expected_reason,
        "actual": actual_reason,
    }

    # 3. must_call
    must_call = expected.get("must_call", [])
    missing_calls = [name for name in must_call if name not in tool_names_called]
    checks["must_call"] = {
        "pass": len(missing_calls) == 0,
        "expected": must_call,
        "missing": missing_calls,
    }

    # 4. must_not_call
    must_not_call = expected.get("must_not_call", [])
    forbidden_calls = [name for name in must_not_call if name in tool_names_called]
    checks["must_not_call"] = {
        "pass": len(forbidden_calls) == 0,
        "expected_absent": must_not_call,
        "found": forbidden_calls,
    }

    all_pass = all(c["pass"] for c in checks.values())
    return {"all_pass": all_pass, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", default="results", type=pathlib.Path,
                        help="directory of result JSON files (default: results/)")
    parser.add_argument("--conversations", "--dir", default="conversations", type=pathlib.Path,
                        help="directory of conversation scripts (default: conversations/)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print detailed per-check output")
    args = parser.parse_args()

    if not args.conversations.is_dir():
        print(f"ERROR: conversation directory not found: {args.conversations}", file=sys.stderr)
        return 2

    if not args.results.is_dir():
        print(f"ERROR: results directory not found: {args.results}", file=sys.stderr)
        print("Run runner.py first to produce results.", file=sys.stderr)
        return 2

    conversations = load_conversations(args.conversations)
    results = load_results(args.results)

    if not results:
        print("No result files found in", args.results)
        return 2

    total_pass = 0
    total_fail = 0
    total_graded = 0
    failures = []

    print(f"Grading {len(results)} conversation(s) against {len(conversations)} expected script(s)\n")
    print(f"{'ID':<12} {'Runs':>4}  {'Result':<8} Details")
    print("-" * 72)

    for cid in sorted(conversations.keys()):
        expected = conversations[cid].get("expected", {})
        runs = results.get(cid, [])

        if not runs:
            print(f"{cid:<12} {'0':>4}  {'SKIP':<8} No result file found")
            continue

        # Grade the WORST run (as per schema.md: "We score your worst run")
        worst_grade = None
        for run in runs:
            grade = grade_single(run, expected, args.verbose)
            if worst_grade is None or (not grade["all_pass"] and worst_grade["all_pass"]):
                worst_grade = grade

        total_graded += 1
        if worst_grade["all_pass"]:
            total_pass += 1
            print(f"{cid:<12} {len(runs):>4}  {'PASS':<8}")
        else:
            total_fail += 1
            fail_reasons = []
            for check_name, check_result in worst_grade["checks"].items():
                if not check_result["pass"]:
                    if check_name == "terminal_state":
                        fail_reasons.append(
                            f"terminal_state: expected={check_result['expected']}, "
                            f"got={check_result['actual']}"
                        )
                    elif check_name == "escalation_reason":
                        fail_reasons.append(
                            f"escalation_reason: expected={check_result['expected']}, "
                            f"got={check_result['actual']}"
                        )
                    elif check_name == "must_call":
                        fail_reasons.append(
                            f"must_call missing: {check_result['missing']}"
                        )
                    elif check_name == "must_not_call":
                        fail_reasons.append(
                            f"must_not_call found: {check_result['found']}"
                        )
            detail = "; ".join(fail_reasons)
            print(f"{cid:<12} {len(runs):>4}  {'FAIL':<8} {detail}")
            failures.append(cid)

        if args.verbose:
            for check_name, check_result in worst_grade["checks"].items():
                status = "✓" if check_result["pass"] else "✗"
                print(f"    {status} {check_name}: {json.dumps(check_result, default=str)}")

    print("-" * 72)
    print(f"\nSummary: {total_pass}/{total_graded} passed, {total_fail} failed")

    if failures:
        print(f"Failed: {', '.join(failures)}")

    # Score
    if total_graded > 0:
        score = total_pass / total_graded * 100
        print(f"Score: {score:.1f}%")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
