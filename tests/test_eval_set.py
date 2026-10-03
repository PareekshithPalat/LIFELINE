"""
Reliability gate: every labelled case in tests/eval/retrieval_eval.json must route to
the expected protocol, and every off-domain / no-protocol case must ABSTAIN. The mobile
app runs the same file in its integration tests.
"""
import json
import os
import pytest

CASES = json.load(open(os.path.join(os.path.dirname(__file__), "eval", "retrieval_eval.json"),
                       encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["q"][:50] for c in CASES])
def test_eval_case(pipeline, profile, case):
    resp = pipeline.process_query(case["q"], profile, allow_cache=False)
    if case["expected"] is None:
        assert resp.verdict.value == "INSUFFICIENT", f"should abstain, got {resp.citations[:1]}"
        assert resp.citations == []
    else:
        assert resp.verdict.value in ("SUFFICIENT", "CONFLICT")
        got = resp.citations[0].evidence_id
        assert got == case["expected"] or got in case.get("also_ok", []), got
        assert resp.immediate_actions, "a protocol answer must contain actions"


def test_no_false_accepts_margin(pipeline, profile):
    """Off-domain questions must stay clearly below the acceptance threshold."""
    from edge.config import get_retrieval_config
    accept = get_retrieval_config()["gate"]["accept_confidence"]
    worst = max(pipeline.process_query(c["q"], profile, allow_cache=False).confidence
                for c in CASES if c["expected"] is None)
    assert worst < accept - 0.01
