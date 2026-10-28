#!/usr/bin/env python3
"""Live integration: pinned Archon scripts + configured fresh agent CLI.
Requires Bun, authenticated GitHub CLI and an agent command returning JSON.
This integration is experimental until validated on the operator's disposable repo.
"""

import json
import os
import pathlib
import subprocess
import sys

import yaml

from .runtime import RUNTIME_GUIDANCE, github_config, github_env

B = pathlib.Path(__file__).resolve().parents[2]
req = json.load(sys.stdin)
ctx = req["context"]
root = pathlib.Path(req["artifacts_dir"])
source = pathlib.Path(req["source_root"])
stage = req["stage"]
out = req["outputs"]
prev = req["previous"]
repo = ctx["repo"]
n = req["round"]
config = github_config(ctx["command_config"])
agent = config["agent_argv"]
runid = root.name


def text(v):
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def git(*args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def execution(name):
    return {
        "path": name,
        "invocation": {"loopPath": [{"groupId": "rounds", "iteration": n}]},
        "attempt": {"checkoutStart": {"kind": "git", "commit": git("rev-parse", "HEAD")}},
    }


env = {
    **github_env(os.environ),
    "ARTIFACTS_DIR": str(root),
    "WORKFLOW_ID": runid,
    "ARCHON_NODE_EXECUTION": json.dumps(execution(stage)),
}
forge = json.loads((root / "forge.json").read_text()) if (root / "forge.json").exists() else {}
if forge.get("source", "gh") != "gh":
    raise ValueError("This run selected an Archon forge plugin; start a new DAGU/gh run")
inputs = {
    "work": ctx["work"],
    "work_order": ctx["work"],
    "pull_request": ctx["pull_request"],
    "branch": ctx["branch"],
    "part": ctx["part"],
    "errors": ctx["errors"],
    "source": forge.get("source", "gh"),
    "pr": out.get("pr", {}),
    "scope": out.get("pr", {}),
    "prior_report": prev.get("prior_report", ""),
    "light": prev.get("light_review", False),
    "draft": "true",
    "publish_description": "true",
    "contract_left": prev.get("contract_left"),
}
env["TYPED_ARTIFACTS_FILE"] = str(root / f"typed-{n}.json")
for k, v in inputs.items():
    env["INPUTS_" + k.upper()] = text(v)


def script(relative, bindings=None):
    e = {**env, **{"INPUTS_" + k.upper(): text(v) for k, v in (bindings or {}).items()}}
    p = subprocess.run(
        ["bun", str(source / relative)], cwd=repo, env=e, text=True, capture_output=True
    )
    if p.stderr:
        print(p.stderr, file=sys.stderr, end="")
    if p.returncode:
        raise RuntimeError(p.stderr or relative + " failed")
    return json.loads(p.stdout)


def schema_for(folder, filename, node):
    d = yaml.safe_load((source / folder / filename).read_text())
    return next(x for x in d["nodes"] if x["id"] == node).get("output_format")


def checked_agent(prompt_name, schema=None, extra=None, readonly=False):
    p = (B / "prompts" / (prompt_name + ".md")).read_text()
    values = {
        **{"$INPUTS." + k: text(v) for k, v in inputs.items()},
        "$ARTIFACTS_DIR": str(root),
        "$WORKFLOW_ID": runid,
        "$ARGUMENTS": ctx["work"],
        "$ARCHON_CLI_COMMAND": "[]",
        "$TYPED_ARTIFACTS_FILE": str(root / f"typed-{n}.json"),
        "$LOOP_PREV_OUTPUT": text(out.get("previous_turn", "")),
    }
    values["$route.output"] = text(out.get("route", {}))
    mode_path = root / f"mode-{n}.json"
    mode = json.loads(mode_path.read_text()) if mode_path.exists() else {}
    for k, v in mode.items():
        values["$mode.output." + k] = text(v)
    if extra:
        values.update(extra)
    for k in sorted(values, key=len, reverse=True):
        p = p.replace(k, values[k])
    p += RUNTIME_GUIDANCE
    p += "\n\nDAGU stage context (authoritative bound inputs):\n" + json.dumps(
        {
            "inputs": inputs,
            "previous_round": prev,
            "current_outputs": out,
            "execution": execution(stage),
            "feedback": ctx.get("feedback", ""),
        },
        indent=2,
    )
    p += "\nReturn exactly one JSON object on stdout, without Markdown fences or other prose. Write requested reports to the artifacts directory.\n"
    if schema:
        p += "Required JSON Schema:\n" + json.dumps(schema)
    before = (
        git("rev-parse", "HEAD")
        + "\n"
        + git("status", "--porcelain", "--untracked-files=all")
        + "\n"
        + git("diff", "HEAD", "--binary")
        if readonly
        else ""
    )
    q = subprocess.run(agent, input=p, cwd=repo, env=env, text=True, capture_output=True)
    if q.stderr:
        print(q.stderr, file=sys.stderr, end="")
    if q.returncode:
        raise RuntimeError("Agent CLI failed: " + q.stderr[-1000:])
    if readonly and before != git("rev-parse", "HEAD") + "\n" + git(
        "status", "--porcelain", "--untracked-files=all"
    ) + "\n" + git("diff", "HEAD", "--binary"):
        raise RuntimeError("Read-only reviewer modified checkout")
    result = json.loads(q.stdout)
    from .engine import schema_check

    schema_check(result, schema)
    # The configured agent command must return the stage object, not a provider envelope.
    return result


if stage == "forge":
    result = script("deliver/scripts/forge-check.ts")
elif stage in ["implement", "reshape"]:
    prompt = "implement"
    extra = {}
    if stage == "implement":
        context = (B / "prompts/implement-delivery-context.md").read_text()
        for k in sorted(inputs, key=len, reverse=True):
            context = context.replace("$INPUTS." + k, text(inputs[k]))
        context = context.replace("$ARTIFACTS_DIR", str(root)).replace(
            "$LOOP_PREV.round.output.summary", prev.get("summary", "")
        )
        extra["$INPUTS.work"] = context
    else:
        context = (
            (B / "prompts/reshape.md")
            .read_text()
            .replace("$INPUTS.work", ctx["work"])
            .replace("$ARTIFACTS_DIR", str(root))
            .replace("$pr.output.head", out["pr"]["head"])
        )
        extra["$INPUTS.work"] = context
    result = checked_agent(
        prompt, schema_for("implement", "archon-implement.yaml", "implement"), extra
    )
elif stage == "pr":
    intent = checked_agent("pr", schema_for("pr", "archon-pr.yaml", "prepare"), readonly=False)
    result = script(
        "pr/scripts/publish-pr.ts",
        {
            **intent,
            "draft": "true",
            "publish_description": "true",
            "pull_request": ctx["pull_request"],
            "branch": ctx["branch"],
        },
    )
elif stage == "scope":
    (root / "review").mkdir(exist_ok=True)
    result = checked_agent(
        "scope", schema_for("review", "archon-review-block.yaml", "scope"), readonly=True
    )
    if result["head_matches"]:
        mode = script(
            "review/scripts/review-round.ts",
            {
                "prior_report": inputs["prior_report"],
                "light": text(inputs["light"]),
                "part": ctx["part"],
            },
        )
        (root / f"mode-{n}.json").write_text(json.dumps(mode))
elif stage == "route":
    result = checked_agent(
        "route", schema_for("review", "archon-review-block.yaml", "route"), readonly=True
    )
elif stage in ["seams", "code", "tests", "errors", "docs"]:
    result = checked_agent(
        stage,
        {
            "type": "object",
            "properties": {"completed": {"type": "boolean"}, "findings": {"type": "array"}},
            "required": ["completed", "findings"],
        },
        readonly=True,
    )
    report = root / "review" / (stage + ".md")
    if not report.is_file() or not report.stat().st_size:
        raise RuntimeError("Reviewer did not write " + str(report))
elif stage in ["review", "rereview"]:
    if stage == "rereview":
        inputs["prior_report"] = str(root / "review/report.md")
        inputs["light"] = True
        scope_again = checked_agent(
            "scope", schema_for("review", "archon-review-block.yaml", "scope"), readonly=True
        )
        if not scope_again["head_matches"]:
            raise RuntimeError(
                "Head changed during reshape rereview; needs operator reconciliation"
            )
        (root / f"mode-{n}.json").write_text(
            json.dumps(
                script(
                    "review/scripts/review-round.ts",
                    {"prior_report": inputs["prior_report"], "light": "true", "part": ctx["part"]},
                )
            )
        )
        # A light rereview must include an independent code lens before synthesis.
        code_result = checked_agent(
            "code",
            {
                "type": "object",
                "properties": {"completed": {"type": "boolean"}, "findings": {"type": "array"}},
                "required": ["completed", "findings"],
            },
            readonly=True,
        )
    if stage == "rereview":
        codefile = root / f"round-{n}/rereview-code.json"
        codefile.write_text(json.dumps(code_result))
        listing = {
            "artifactsByType": {
                "review-lens": [
                    {
                        "path": str(codefile.relative_to(root)),
                        "nodeId": "code",
                        "loopGroupPath": [{"groupId": "rounds", "iteration": n}],
                    }
                ]
            },
            "errors": [],
        }
        (root / f"typed-{n}.json").write_text(json.dumps(listing))
    policy = script("review/scripts/policy.ts")
    try:
        result = checked_agent(
            "review",
            schema_for("review", "archon-review-block.yaml", "synthesize"),
            {"$INPUTS.policy_defaults": text(policy["defaults"])},
            readonly=True,
        )
    finally:
        script("review/scripts/prune-scratch.ts", {"lens": ""})
elif stage in ["publish-review", "publish-rereview"]:
    verdict = out["review" if stage == "publish-review" else "rereview"]
    scope = out["scope"]
    mode = json.loads((root / f"mode-{n}.json").read_text())
    result = script(
        "review/scripts/publish-review.ts",
        {
            "scope": inputs["scope"],
            "pr": scope["pr"],
            "report": str(root / "review/report.md"),
            "head": mode["head"],
            "ready": verdict["ready"],
            "action": verdict["action"],
            "summary": verdict["findings_summary"],
            "report_pointer": verdict["report"],
            "discoveries": verdict["discoveries"],
            "contract_left": verdict["contract_left"],
        },
    )
elif stage == "simplify":
    try:
        result = checked_agent(
            "simplify", schema_for("simplify", "archon-simplify.yaml", "simplify"), readonly=True
        )
    finally:
        script("simplify/scripts/prune-scratch.ts", {"lens": "simplify"})
elif stage == "settle-threads":
    result = checked_agent(
        "settle-threads",
        json.loads((B / "schemas.json").read_text())["settle-threads"],
        readonly=True,
    )
elif stage == "ci":
    result = checked_agent("ci", json.loads((B / "schemas.json").read_text())["ci"], readonly=True)
elif stage == "threads":
    result = script(
        "deliver/scripts/threads.ts",
        {"pr": out["pr"], "answers": out.get("settle-threads", {}).get("answers")},
    )
elif stage == "update-pr-body":
    inputs["pr"] = prev["pr_url"]
    inputs["contract_left"] = prev["contract_left"]
    result = checked_agent(
        "update-pr-body",
        json.loads((B / "schemas.json").read_text()).get("update-pr-body"),
        readonly=True,
    )
else:
    raise ValueError(stage)
print(json.dumps(result))
