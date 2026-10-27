#!/usr/bin/env python3
import itertools
import json
import pathlib
import subprocess
import uuid

from archon_dagu.engine import STAGES
from archon_dagu.local_runner import run

B = pathlib.Path(__file__).resolve().parents[1]
(B / ".runs").mkdir(exist_ok=True)
CASES = {
    "ready": ([{}], True, "delivered", 1),
    "implementation_broke_tests": (
        [{"implement": {"green": False, "red_cause": "introduced"}}],
        False,
        "implement_blocked",
        1,
    ),
    "implementation_incomplete": (
        [{"implement": {"green": False, "red_cause": "incomplete"}}],
        False,
        "implement_blocked",
        1,
    ),
    "inherited_failure": (
        [{"implement": {"green": False, "red_cause": "inherited"}}],
        True,
        "delivered",
        1,
    ),
    "environment_failure": (
        [{"implement": {"green": False, "red_cause": "environment"}}],
        True,
        "delivered",
        1,
    ),
    "review_needs_fix": (
        [{"review": {"ready": False, "action": "correct"}}, {}],
        True,
        "delivered",
        2,
    ),
    "review_needs_replan": ([{"review": {"ready": False, "action": "replan"}}], False, "replan", 1),
    "review_needs_person": ([{"review": {"ready": False, "action": "ask"}}], False, "ask", 1),
    "fix_ci": ([{"ci": {"state": "pr_caused"}}, {}], True, "delivered", 2),
    "ci_external_problem": ([{"ci": {"state": "other"}}], False, "ci_other", 1),
    "fix_threads": ([{"threads": {"open": 2}}, {}], True, "delivered", 2),
    "thread_needs_person": (
        [{"threads": {"open": 1}}, {"settle-threads": {"ask": True}, "threads": {"open": 1}}],
        False,
        "ask",
        2,
    ),
    "four_round_cap": ([{"ci": {"state": "pr_caused"}}], False, "round_cap", 4),
    "simplify_then_rereview": ([{"simplify": {"findings": True}}], True, "delivered", 1),
    "rereview_rejects_reshape": (
        [{"simplify": {"findings": True}, "rereview": {"ready": False, "action": "correct"}}, {}],
        True,
        "delivered",
        2,
    ),
    "rereview_needs_person": (
        [{"simplify": {"findings": True}, "rereview": {"ready": False, "action": "ask"}}],
        False,
        "ask",
        1,
    ),
    "head_changed": ([{"scope": {"head_matches": False}}], False, "ask", 1),
    "specialist_failed": ([{"fail": "code"}, {}], True, "delivered", 2),
    "forge_unavailable": ([{"fail": "forge"}], False, "failed", 0),
    "pr_publish_failed": ([{"fail": "pr"}], False, "failed", 0),
    "threads_unreadable": ([{"fail": "threads"}], False, "failed", 0),
    "body_update_failed": ([{"fail": "update-pr-body"}], False, "failed", 1),
    "contract_items_left": (
        [{"review": {"contract_left": ["Operator must verify production configuration"]}}],
        True,
        "delivered",
        1,
    ),
    "discovery_relay": (
        [
            {
                "review": {
                    "discoveries": [
                        {
                            "title": "Unrelated base defect",
                            "claim": "Existing defect outside this change",
                            "evidence": ["fixture log"],
                            "relation": "unrelated",
                            "source_nodes": ["code"],
                        }
                    ]
                }
            }
        ],
        True,
        "delivered",
        1,
    ),
    "keeps_simplify_once": (
        [
            {"simplify": {"findings": True}, "ci": {"state": "pr_caused"}},
            {"simplify": {"findings": True}},
        ],
        True,
        "delivered",
        2,
    ),
    "implementation_turn_cap": ([{"implement": {"done": False}}], False, "failed", 0),
}
for k, (rounds, *_) in CASES.items():
    (B / "examples/fixtures" / (k + ".json")).write_text(
        json.dumps({"rounds": rounds}, indent=2) + "\n"
    )
# Explicit test-only commands exercise both live transports without external effects.
config = {
    "test_transport": True,
    "commands": {
        s: ["python", "-m", "archon_dagu.mock_stage"]
        for s in ["forge", *STAGES[:-1], "update-pr-body"]
    },
}
(B / ".runs/test-commands.json").write_text(json.dumps(config, indent=2) + "\n")
repo = B / ".runs/mock-checkout"
repo.mkdir(exist_ok=True)
subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
results = []
for shape, mode in itertools.product(["simple", "detailed"], ["dry", "real"]):
    for case, (_, ready, reason, roundno) in CASES.items():
        state = B / ".runs/runs" / f"{shape}-{mode}-{case}-{uuid.uuid4().hex[:6]}"
        params = {
            "project_dir": str(B),
            "state_dir": str(state),
            "repo": str(repo),
            "fixture": str(B / "examples/fixtures" / (case + ".json")),
            "commands": str(B / ".runs/test-commands.json"),
            "work": "Accepted fixture work; no external operations",
        }
        failed = False
        error = None
        try:
            trace = run(B / "workflows" / f"{shape}-{mode}.yaml", params)
        except Exception as e:
            failed = True
            error = str(e)
            trace = {"error": error}
        report = (
            json.loads((state / "report.json").read_text())
            if (state / "report.json").exists()
            else {}
        )
        ok = (
            report.get("ready") == ready
            and report.get("reason") == reason
            and report.get("round") == roundno
            and failed == (reason == "failed")
            and report.get("merged") is False
        )
        if case == "discovery_relay":
            ok = ok and "Unrelated base defect" in report.get("summary", "")
        if case == "contract_items_left":
            ok = ok and "Operator must verify" in report.get("summary", "")
        (state / "harness-trace.json").write_text(json.dumps(trace, indent=2) + "\n")
        results.append(
            {
                "variant": shape + "-" + mode,
                "case": case,
                "passed": ok,
                "real_effects": "mocked" if mode == "real" else "fixtures",
                "report": report,
                "error": error,
                "path": str(state),
            }
        )
        print(shape, mode, case, "PASS" if ok else "FAIL", flush=True)
(B / ".runs/cases.json").write_text(json.dumps(results, indent=2) + "\n")
assert all(x["passed"] for x in results)
print(len(results), "YAML-command cases passed; not DAGU runtime runs")
