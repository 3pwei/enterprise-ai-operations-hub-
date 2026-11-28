"""Run the fixed knowledge cases against a running developer-mode HTTP API."""

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

CASES = Path(__file__).resolve().parents[1] / "tests/fixtures/knowledge_cases.json"


def verify_citations(case, citations):
    refs = [f"{c['document_id']}@{c['version']}#{c['paragraph']}" for c in citations]
    expected = [case["reference"]] if case["reference"] else []
    if refs != expected:
        raise AssertionError(f"{case['id']}: expected {expected}, got {refs}")
    if expected and case["excerpt"] not in citations[0]["excerpt"]:
        raise AssertionError(f"{case['id']}: reference does not contain the expected evidence")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--strategy", default="keyword+pgvector")
    args = parser.parse_args()
    tokens = {role: os.getenv(f"DEMO_{role.upper()}_TOKEN") for role in ("analyst", "manager")}
    if not all(tokens.values()):
        parser.error("Set DEMO_ANALYST_TOKEN and DEMO_MANAGER_TOKEN")
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    for case in cases:
        body = json.dumps({"message": case["message"], "filters": case["filters"]}).encode()
        request = Request(f"{args.url.rstrip('/')}/api/knowledge/query", data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {tokens[case['role']]}",
        })
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        verify_citations(case, result["citations"])
        for citation in result["citations"]:
            if citation["excerpt"] not in result["answer"]:
                raise AssertionError(f"{case['id']}: missing quoted passage")
        status = "answered" if case["reference"] else "no_evidence"
        trace = result["trace"][0]
        if result["status"] != status or result["mode"] != "mock" or trace["strategy"] != args.strategy:
            raise AssertionError(f"{case['id']}: unexpected result mode, status, or search strategy")
        print(f"PASS {case['id']} ({trace['strategy']})")
    print(f"{len(cases)}/{len(cases)} cases passed")


if __name__ == "__main__":
    main()
