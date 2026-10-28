#!/usr/bin/env python3
"""Reference adapter boundary and deterministic Archon delivery reducer.
Simulation never invokes a subprocess. Real mode requires an explicit adapter argv.
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

from .runtime import github_config

BASE = pathlib.Path(__file__).resolve().parents[2]
SOURCE = BASE / "vendor/archon/.archon/workflows/sdlc"
STAGES = [
    "implement",
    "pr",
    "scope",
    "route",
    "seams",
    "code",
    "tests",
    "errors",
    "docs",
    "review",
    "publish-review",
    "simplify",
    "reshape",
    "rereview",
    "publish-rereview",
    "settle-threads",
    "ci",
    "threads",
    "reduce",
]
LENSES = ["seams", "code", "tests", "errors", "docs"]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, indent=2)
    os.replace(name, path)


def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def decide(v, previous=None):
    """Same verdict precedence and four-round cap as pinned Archon round.ts."""
    previous = previous or {}
    impl = v["implement"]
    review = v.get("rereview") or v.get("review") or {}
    ci = v.get("ci", {})
    threads = v.get("threads", {})
    settle = v.get("settle-threads", {})
    handed = impl["green"] or impl["red_cause"] in ["inherited", "environment"]
    again = False
    if not handed:
        reason = "implement_blocked"
    elif review.get("ready") is not True:
        reason = (
            review.get("action") if review.get("action") in ["ask", "replan"] else "review_open"
        )
        again = reason == "review_open"
    elif ci.get("state") == "pr_caused":
        reason, again = "ci_pr_caused", True
    elif ci.get("state") != "green":
        reason = "ci_other"
    elif threads.get("open", 0) > 0:
        reason = "ask" if settle.get("ask") else "threads_open"
        again = reason == "threads_open"
    else:
        reason = "delivered"
    n = previous.get("round", 0) + 1
    capped = again and n >= 4
    return dict(
        round=n,
        done=not again or capped,
        ready=reason == "delivered",
        reason="round_cap" if capped else reason,
        pr_url=v.get("pr", {}).get("url", previous.get("pr_url", "")),
        prior_report=f"round-{n}/review.json" if review else previous.get("prior_report", ""),
        light_review=reason == "ci_pr_caused",
        contract_left=review.get("contract_left", previous.get("contract_left")),
        summary=f"Round {n}: {reason}" + (" at the 4-round cap" if capped else ""),
    )


def validate(stage, r):
    if not isinstance(r, dict):
        raise ValueError(stage + ": output must be an object")

    def boolean(k):
        if type(r.get(k)) is not bool:
            raise ValueError(stage + ": " + k + " must be boolean")

    if stage in ["implement", "reshape"]:
        boolean("green")
        if r.get("red_cause") not in ["", "introduced", "inherited", "environment", "incomplete"]:
            raise ValueError("invalid red_cause")
    if stage in ["review", "rereview"]:
        boolean("ready")
        if r.get("action") not in ["none", "correct", "ask", "replan"]:
            raise ValueError("invalid review action")
        if not isinstance(r.get("contract_left"), list):
            raise ValueError("missing contract_left")
    if stage == "ci" and r.get("state") not in ["green", "pr_caused", "other"]:
        raise ValueError("invalid CI state")
    if stage == "threads" and (type(r.get("open")) is not int or r["open"] < 0):
        raise ValueError("invalid thread count")
    if stage == "simplify":
        boolean("findings")
    if stage == "settle-threads":
        boolean("ask")
    if stage in LENSES:
        boolean("completed")
    if stage == "forge" and r.get("source") not in ["gh", "forge"]:
        raise ValueError("invalid forge source")
    if stage == "scope":
        boolean("head_matches")
    if stage == "route":
        for lens in LENSES:
            boolean(lens)
    if stage == "pr":
        if not isinstance(r.get("url"), str) or not r["url"]:
            raise ValueError("missing qualified PR URL")
        if not isinstance(r.get("repo"), dict) or type(r.get("number")) is not int:
            raise ValueError("missing qualified PR identity")
    return r


def fixture_output(stage, spec):
    defaults = {
        "forge": dict(source="gh"),
        "publish-review": dict(published=True),
        "publish-rereview": dict(published=True),
        "implement": dict(
            done=True, green=True, red_cause="", summary="fixture focused checks pass"
        ),
        "pr": dict(
            repo=dict(host="github.com", path="example/repo"),
            number=42,
            url="https://github.com/example/repo/pull/42",
            head="fixture",
            base="main",
            is_draft=True,
        ),
        "scope": dict(head_matches=True),
        "route": dict(seams=True, code=True, tests=True, errors=False, docs=False),
        "review": dict(
            ready=True,
            action="none",
            contract_left=[],
            discoveries=[],
            summary="fixture review passed",
        ),
        "simplify": dict(findings=False),
        "reshape": dict(green=True, red_cause=""),
        "rereview": dict(ready=True, action="none", contract_left=[], discoveries=[]),
        "settle-threads": dict(answers=[], ask=False, summary="fixture dispositions verified"),
        "ci": dict(state="green", rerun="none", summary="fixture checks pass"),
        "threads": dict(open=0, summary="fixture no unresolved threads"),
        "update-pr-body": dict(changed=False, summary="fixture body accurate"),
    }
    if stage in LENSES:
        defaults[stage] = dict(completed=True, findings=[])
    if spec.get("fail") == stage:
        raise RuntimeError("fixture injected failure: " + stage)
    r = defaults[stage].copy()
    r.update(spec.get(stage, {}))
    return validate(stage, r)


def context(root):
    return load(root / "context.json")


def schema_check(value, schema, path="output"):
    if not schema:
        return
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    checks = {
        "null": lambda v: v is None,
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "boolean": lambda v: type(v) is bool,
        "integer": lambda v: type(v) is int,
        "number": lambda v: type(v) in [int, float],
        "string": lambda v: isinstance(v, str),
    }
    if types and not any(checks[t](value) for t in types):
        raise ValueError(path + ": wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path + ": invalid enum")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                raise ValueError(path + ": missing " + k)
        for k, v in value.items():
            if k in schema.get("properties", {}):
                schema_check(v, schema["properties"][k], path + "." + k)
        if value.get("type") == "archon_artifact":
            if (
                not isinstance(value.get("path"), str)
                or pathlib.PurePath(value["path"]).is_absolute()
                or ".." in pathlib.PurePath(value["path"]).parts
            ):
                raise ValueError("artifact path escapes run")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(path + ": too few entries")
        for i, v in enumerate(value):
            schema_check(v, schema.get("items", {}), path + "." + str(i))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or (
            "pattern" in schema and not re.search(schema["pattern"], value)
        ):
            raise ValueError(path + ": invalid text")
    if type(value) in [int, float] and "minimum" in schema and value < schema["minimum"]:
        raise ValueError(path + ": too small")


def preflight():
    mode = os.environ.get("PORT_MODE", "dry")
    if mode not in ["dry", "real"]:
        raise ValueError("mode must be dry or real")
    if not shutil.which("node"):
        raise RuntimeError("Node.js 24 is required to run the original Archon reducer")
    manifest = load(BASE / "SOURCE.json")
    for path, digest in manifest["hashes"].items():
        if hashlib.sha256((SOURCE / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Pinned source changed: " + path)
    if mode == "dry":
        fixture = load(pathlib.Path(os.environ["FIXTURE"]))
        if not fixture or not fixture.get("rounds"):
            raise ValueError("fixture needs nonempty rounds")
        print(json.dumps({"mode": mode, "source_commit": manifest["commit"], "network_calls": 0}))
        return
    path = pathlib.Path(os.environ["STAGE_COMMANDS"])
    cfg = load(path)
    cfg = github_config(cfg) if cfg else None
    if not cfg or not isinstance(cfg.get("commands"), dict):
        raise RuntimeError("Live stage commands are not configured: " + str(path))
    for executable in cfg.get("requires", []):
        if not shutil.which(executable):
            raise RuntimeError("Missing live prerequisite: " + executable)
    for name in ["forge", *STAGES[:-1], "update-pr-body"]:
        argv = cfg["commands"].get(name)
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
            raise RuntimeError("Missing argv command for " + name)
        if not shutil.which(argv[0]):
            raise RuntimeError("Executable unavailable for " + name + ": " + argv[0])
    repo = pathlib.Path(os.environ["TARGET_REPO"]).resolve()
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=repo, text=True, capture_output=True
    )
    if r.returncode:
        raise RuntimeError("Live mode requires an explicit isolated Git checkout")
    if not os.environ.get("WORK", "").strip():
        raise RuntimeError("Live mode requires accepted work; it does not triage or plan")
    print(
        json.dumps(
            {
                "mode": mode,
                "commands": len(cfg["commands"]),
                "test_transport": cfg.get("test_transport", False),
            }
        )
    )


def invoke(root, stage, spec, n, v):
    ctx = context(root)
    if ctx["mode"] == "dry":
        return fixture_output(stage, spec)
    cfg = ctx["command_config"]
    argv = cfg["commands"][stage]
    request = dict(
        stage=stage,
        round=n,
        context=ctx,
        previous=load(root / "state.json", {}),
        outputs=v,
        prompt_file=str(BASE / "prompts" / (stage + ".md")),
        source_root=str(SOURCE),
        artifacts_dir=str(root),
        fixture=spec,
    )
    save(root / "requests" / f"{n}-{stage}.json", request)
    p = subprocess.run(
        argv, input=json.dumps(request), text=True, capture_output=True, cwd=ctx["repo"]
    )
    (root / "requests" / f"{n}-{stage}.stderr.log").write_text(p.stderr)
    if p.returncode:
        raise RuntimeError(stage + " command failed: " + p.stderr[-1000:])
    result = validate(stage, json.loads(p.stdout))
    if not cfg.get("test_transport"):
        schema = load(BASE / "schemas.json", {}).get(stage)
        schema_check(result, schema)

        def pointers(x):
            if isinstance(x, dict):
                if x.get("type") == "archon_artifact":
                    f = (root / x["path"]).resolve()
                    if not f.is_relative_to(root.resolve()):
                        raise ValueError("Artifact symlink escapes run")
                    if not f.is_file() or f.stat().st_size == 0:
                        raise ValueError("Missing nonempty certified artifact: " + str(f))
                for z in x.values():
                    pointers(z)
            elif isinstance(x, list):
                for z in x:
                    pointers(z)

        pointers(result)
    return result


def initialize(root):
    mode = os.environ.get("PORT_MODE", "dry")
    if mode not in ["dry", "real"]:
        raise ValueError("invalid mode")
    root.mkdir(parents=True, exist_ok=True)
    if (root / "context.json").exists():
        raise RuntimeError("STATE_DIR already used; use a new directory per batch")
    cfg = (
        load(pathlib.Path(os.environ.get("STAGE_COMMANDS", "/nonexistent")), {})
        if mode == "real"
        else {}
    )
    cfg = github_config(cfg)
    if mode == "real" and not cfg.get("commands"):
        raise RuntimeError("Live mode has no stage commands; refusing execution")
    repo = str(pathlib.Path(os.environ.get("TARGET_REPO", ".")).resolve())
    spec = (
        load(pathlib.Path(os.environ["FIXTURE"]))
        if mode == "dry" or cfg.get("test_transport")
        else {"rounds": [{}]}
    )
    save(
        root / "context.json",
        dict(
            mode=mode,
            fixture=spec,
            command_config=cfg,
            repo=repo,
            work=os.environ.get("WORK", ""),
            pull_request=os.environ.get("PULL_REQUEST", ""),
            branch=os.environ.get("BRANCH", ""),
            part=os.environ.get("PART", ""),
            errors=os.environ.get("ERRORS", "auto"),
            feedback=os.environ.get("FEEDBACK", ""),
        ),
    )
    save(root / "state.json", dict(round=0, done=False, ready=False, pr_url="", contract_left=None))
    forge = invoke(root, "forge", spec["rounds"][0], 0, {})
    if forge.get("source") not in ["gh", "forge"]:
        raise ValueError("Invalid forge preflight source")
    save(root / "forge.json", forge)
    print(json.dumps({"mode": mode, "state_dir": str(root)}))


def eligible(stage, v, prev):
    impl = v.get("implement", {})
    handed = impl.get("green") is True or impl.get("red_cause") in ["inherited", "environment"]
    if stage == "implement":
        return True
    if stage == "reduce":
        return True
    if not handed:
        return False
    if stage in ["pr", "scope"]:
        return True
    if stage == "publish-review":
        return v["scope"]["head_matches"]
    if stage == "publish-rereview":
        return "rereview" in v
    if stage == "route":
        return v["scope"]["head_matches"] and not prev.get("light_review", False)
    if stage in LENSES:
        return v["scope"]["head_matches"] and (
            stage == "code" if prev.get("light_review") else v.get("route", {}).get(stage, False)
        )
    if stage == "review":
        return True
    if stage == "simplify":
        return v["review"]["ready"]
    if stage in ["reshape", "rereview"]:
        return v.get("simplify", {}).get("findings", False)
    if stage == "settle-threads":
        return prev.get("threads_open", 0) > 0
    if stage == "ci":
        return (v.get("rereview") or v.get("review", {})).get("ready", False)
    if stage == "threads":
        return True
    raise ValueError(stage)


def stage(root, name):
    prev = load(root / "state.json")
    n = prev["round"] + 1
    if prev["done"]:
        print(json.dumps({"noop": True, "stage": name}))
        return
    rd = root / f"round-{n}"
    rd.mkdir(exist_ok=True)
    v = {p.stem: load(p) for p in rd.glob("*.json")}
    if not eligible(name, v, prev):
        print(json.dumps({"skipped": name}))
        return
    if (rd / (name + ".json")).exists():
        raise RuntimeError("Stage already recorded; reconcile before retry: " + name)
    if name == "reduce":
        result = original_reduce(root, v, prev)
        result["threads_open"] = v.get("threads", {}).get("open", 0)
        save(rd / "reduce.json", result)
        save(root / "state.json", result)
    else:
        specs = context(root)["fixture"]["rounds"]
        spec = specs[min(n - 1, len(specs) - 1)]
        if name == "review" and not v["scope"]["head_matches"]:
            result = dict(
                ready=False,
                action="ask",
                contract_left=["PR head mismatch prevented contract review."],
            )
        elif name == "simplify" and any(p.parent != rd for p in root.glob("round-*/simplify.json")):
            result = dict(findings=False, summary="Structure was already judged in this batch")
        elif name == "review" and any(v.get(lens, {}).get("completed") is False for lens in LENSES):
            result = invoke(root, name, spec, n, v)
            result.update(
                ready=False,
                action="correct",
                contract_left=["Selected specialist did not complete"],
                findings_summary="Review coverage gap: selected specialist did not complete",
                summary="Review coverage gap",
            )
        else:
            try:
                result = invoke(root, name, spec, n, v)
                if name in ["implement", "reshape"]:
                    turn = 1
                    while result.get("done", True) is False and turn < 5:
                        save(rd / f"{name}-turn-{turn}.json", result)
                        result = invoke(root, name, spec, n, {**v, "previous_turn": result})
                        turn += 1
                    if result.get("done", True) is False:
                        raise RuntimeError("Implementation exhausted its five fresh turns")
            except Exception as e:
                if name not in LENSES:
                    raise
                result = dict(completed=False, findings=[], error=str(e))
        save(rd / (name + ".json"), result)
    typed_listing(root)
    print(json.dumps(result))


def typed_listing(root):
    kinds = {
        "implement": "implementation",
        "reshape": "implementation",
        "pr": "pull-request",
        "review": "review-report",
        "rereview": "review-report",
        "simplify": "structure-review",
        **{lens: "review-lens" for lens in LENSES},
    }
    grouped = {}
    for rd in sorted(root.glob("round-*")):
        for name, kind in kinds.items():
            p = rd / (name + ".json")
            if p.exists() and not (name in LENSES and load(p).get("completed") is False):
                grouped.setdefault(kind, []).append(
                    {
                        "path": str(p.relative_to(root)),
                        "nodeId": name,
                        "loopGroupPath": [
                            {"groupId": "rounds", "iteration": int(rd.name.split("-")[-1])}
                        ],
                    }
                )
    listing = {"artifactsByType": grouped, "errors": []}
    save(root / "typed-all.json", listing)
    current = load(root / "state.json", {}).get("round", 0) + 1
    selected = {
        k: [e for e in entries if e["loopGroupPath"][0]["iteration"] == current]
        for k, entries in grouped.items()
    }
    save(root / f"typed-{current}.json", {"artifactsByType": selected, "errors": []})


def source_script(root, name, bindings):
    env = {
        **os.environ,
        "ARTIFACTS_DIR": str(root),
        "TYPED_ARTIFACTS_FILE": str(root / "typed-all.json"),
    }
    for k, v in bindings.items():
        env["INPUTS_" + k.upper()] = (
            v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))
        )
    p = subprocess.run(
        ["node", "--experimental-transform-types", str(SOURCE / f"deliver/scripts/{name}.ts")],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(p.stdout)


def finalize(root, failure=False):
    s = load(root / "state.json", {})
    typed_listing(root)
    if failure:
        r = source_script(root, "report", {"outcome": None})
    else:
        if s.get("done") is not True:
            raise RuntimeError("Missing terminal delivery outcome")
        if s.get("pr_url"):
            c = context(root)
            specs = c["fixture"]["rounds"]
            n = s["round"]
            rd = root / f"round-{n}"
            v = {p.stem: load(p) for p in rd.glob("*.json")}
            body = invoke(root, "update-pr-body", specs[min(n - 1, len(specs) - 1)], n, v)
            save(root / "update-pr-body.json", body)
        outcome = source_script(
            root, "outcome", {"rounds": s, "source": load(root / "forge.json")["source"]}
        )
        save(root / "outcome.json", outcome)
        r = source_script(root, "report", {"outcome": outcome})
    r["round"] = s.get("round", 0)
    r["contract_left"] = s.get("contract_left")
    c = context(root) or {"mode": os.environ.get("PORT_MODE", "dry"), "command_config": {}}
    r["simulated"] = c["mode"] == "dry" or c["command_config"].get("test_transport", False)
    r["source_commit"] = "72817c50dc51bb91773f71e5448bb7d387bfc8dd"
    r["merged"] = False
    r["note"] = "Delivery stops at PR readiness; merge stays on the forge"
    r["needs_attention"] = not r["ready"]
    save(root / "report.json", r)
    print(json.dumps(r))


def original_reduce(root, v, previous):
    # Execute the exact upstream file, with its original local io.ts import.
    def j(x):
        return "null" if x is None else json.dumps(x, separators=(",", ":"))

    bindings = {
        "previous": previous.get("round"),
        "prior_report": previous.get("prior_report", ""),
        "previous_pr_url": previous.get("pr_url", ""),
        "previous_contract_left": previous.get("contract_left"),
    }
    for name, k in [
        ("green", "green"),
        ("red_cause", "red_cause"),
        ("implement_summary", "summary"),
    ]:
        bindings[name] = v["implement"].get(k)
    bindings["pr_url"] = v.get("pr", {}).get("url")
    for prefix, node in [("review", v.get("review", {})), ("rereview", v.get("rereview", {}))]:
        for suffix, k in [
            ("ready", "ready"),
            ("action", "action"),
            ("summary", "findings_summary"),
            ("contract_left", "contract_left"),
        ]:
            bindings[prefix + "_" + suffix] = node.get(k)
    bindings.update(
        ci=v.get("ci", {}).get("state"),
        ci_summary=v.get("ci", {}).get("summary"),
        threads_open=v.get("threads", {}).get("open"),
        threads_summary=v.get("threads", {}).get("summary"),
        settle_ask=v.get("settle-threads", {}).get("ask"),
        settle_summary=v.get("settle-threads", {}).get("summary"),
    )
    env = {**os.environ, "ARTIFACTS_DIR": str(root)}
    for k, x in bindings.items():
        env["INPUTS_" + k.upper()] = x if isinstance(x, str) else j(x)
    p = subprocess.run(
        ["node", str(SOURCE / "deliver/scripts/round.ts")],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(p.stdout)


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "command",
        choices=[
            "preflight",
            "init",
            "batch",
            "stage",
            "finalize",
            "failure",
            "ready",
            "attention",
        ],
    )
    p.add_argument("stage", nargs="?")
    a = p.parse_args()
    outer = pathlib.Path(os.environ["STATE_DIR"]).resolve()
    if a.command == "preflight":
        preflight()
        return
    if a.command == "init":
        outer.mkdir(parents=True, exist_ok=True)
        old = load(outer / "active.json")
        if old and not load(pathlib.Path(old["path"]) / "report.json"):
            raise RuntimeError("Existing unfinished batch; reconcile before replay")
        root = outer / "batches" / f"{len(list((outer / 'batches').glob('*'))) + 1:03}"
        save(outer / "active.json", {"path": str(root)})
        initialize(root)
        return
    active = load(outer / "active.json")
    root = pathlib.Path(active["path"]) if active else outer
    if a.command == "batch":
        for _ in range(4):
            if load(root / "state.json")["done"]:
                break
            for name in STAGES:
                stage(root, name)
    elif a.command == "stage":
        stage(root, a.stage)
    elif a.command == "ready":
        print(str(load(root / "report.json")["ready"]).lower())
    elif a.command == "attention":
        report = load(root / "report.json")
        decision = context(root)["fixture"].get("attention", {}).get("decision", "wait")
        result = {
            "state": "done" if report["ready"] or decision == "finish" else "waiting_for_person",
            "simulated": True,
            "reason": report["reason"],
            "choices": [] if report["ready"] else ["rerun", "finish"],
            "merged": False,
        }
        save(outer / "attention.json", result)
        print(json.dumps(result))
    else:
        finalize(root, a.command == "failure")
        save(outer / "report.json", load(root / "report.json"))


if __name__ == "__main__":
    main()
