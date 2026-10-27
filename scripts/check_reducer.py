import json
import pathlib
import random
import subprocess

from archon_dagu.engine import decide

b = pathlib.Path(__file__).resolve().parents[1]
(b / ".runs").mkdir(exist_ok=True)
r = random.Random(42)
inputs = []
expected = []
for _ in range(4096):
    impl = {
        "green": r.choice([True, False]),
        "red_cause": r.choice(["", "introduced", "inherited", "environment", "incomplete"]),
    }
    review = {
        "ready": r.choice([True, False]),
        "action": r.choice(["none", "correct", "ask", "replan"]),
        "contract_left": r.choice([[], ["left"]]),
    }
    again = {
        "ready": r.choice([True, False]),
        "action": r.choice(["none", "correct", "ask", "replan"]),
        "contract_left": [],
    }
    v = {
        "implement": impl,
        "review": review,
        "ci": {"state": r.choice(["green", "pr_caused", "other"])},
        "threads": {"open": r.choice([0, 1, 5])},
        "settle-threads": {"ask": r.choice([True, False])},
        "pr": {"url": "https://example.test/pr/42"},
    }
    if r.choice([True, False]):
        v["rereview"] = again
    prev = {"round": r.choice([0, 1, 2, 3]), "contract_left": None}
    e = {
        "PREVIOUS": prev["round"],
        "GREEN": impl["green"],
        "RED_CAUSE": impl["red_cause"],
        "REVIEW_READY": review["ready"],
        "REVIEW_ACTION": review["action"],
        "REVIEW_CONTRACT_LEFT": review["contract_left"],
        "REREVIEW_READY": v.get("rereview", {}).get("ready"),
        "REREVIEW_ACTION": v.get("rereview", {}).get("action"),
        "REREVIEW_CONTRACT_LEFT": v.get("rereview", {}).get("contract_left"),
        "PREVIOUS_CONTRACT_LEFT": None,
        "CI": v["ci"]["state"],
        "THREADS_OPEN": v["threads"]["open"],
        "SETTLE_ASK": v["settle-threads"]["ask"],
        "PR_URL": v["pr"]["url"],
    }
    inputs.append(
        {"INPUTS_" + k: (x if isinstance(x, str) else json.dumps(x)) for k, x in e.items()}
    )
    expected.append(decide(v, prev))
p = subprocess.run(
    ["node", str(b / "scripts/reducer_oracle.mjs")],
    input=json.dumps(inputs),
    capture_output=True,
    text=True,
    check=True,
)
actual = json.loads(p.stdout)
keys = ["round", "done", "ready", "reason", "light_review", "contract_left", "pr_url"]
for i, (a, e) in enumerate(zip(actual, expected)):
    assert all(a.get(k) == e.get(k) for k in keys), (i, a, e)
result = {
    "cases": len(inputs),
    "passed": True,
    "compared_fields": keys,
    "source": "Original round.ts body with test-only io shim; production engine executes unchanged file",
    "commit": "72817c50dc51bb91773f71e5448bb7d387bfc8dd",
}
(b / ".runs/reducer-parity.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
