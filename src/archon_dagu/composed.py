"""Execute pinned composed Archon graphs with explicit effects and receipts."""

import argparse
import ast
import hashlib
import json
import os
import pathlib
import re
import sys

import yaml

from . import engine
from .standalone import Run, canonical, git, initialize, invoke, load, lock, save

BASE, SOURCE = engine.BASE, engine.SOURCE
ROOTS = {
    "review": "review/archon-review-block.yaml",
    "simplify": "simplify/archon-simplify.yaml",
    "pr": "pr/archon-pr.yaml",
    "ship": "ship/archon-ship-block.yaml",
    "upkeep": "upkeep/archon-upkeep.yaml",
    "issue-response": "../examples/proactive-issue-investigation.yaml",
}
LENSES = ("seams", "code", "tests", "errors", "docs")
REF = re.compile(r"\$([\w-]+)\.output((?:\.[\w-]+)*)")


def source_graph(name):
    return json.loads((BASE / "COMPOSED_SOURCE.json").read_text())["graphs"][name]


def when(expression, lookup):
    """Evaluate only the source's boolean/comparison language, with short circuiting."""
    refs = {}

    def replace(match):
        key = "ref" + str(len(refs))
        refs[key] = (match[1], match[2])
        return key

    text = REF.sub(replace, expression).replace("&&", " and ").replace("||", " or ")
    tree = ast.parse(text, mode="eval")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("true", "false", "null"):
                return {"true": True, "false": False, "null": None}[node.id]
            return lookup(*refs[node.id])
        if isinstance(node, ast.BoolOp):
            return (
                all(visit(v) for v in node.values)
                if isinstance(node.op, ast.And)
                else any(visit(v) for v in node.values)
            )
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b = visit(node.left), visit(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return a == b
            if isinstance(node.ops[0], ast.NotEq):
                return a != b
        raise ValueError("Unsupported source condition")

    return bool(visit(tree))


class Stage(Run):
    def __init__(self, owner, sid):
        self.owner, self.sid = owner, sid
        self.entry = owner.graph[sid]
        super().__init__(owner.root, sources={owner.name: self.entry["source"]})
        self.name = (
            (SOURCE / self.entry["source"]).parent.name
            if owner.name != "issue-response"
            else owner.name
        )
        self.ctx = {
            **self.ctx,
            "inputs": owner.inputs_for(self.entry),
            "prompt_namespace": "composed",
        }
        for key, value in self.ctx["inputs"].items():
            self.env["INPUTS_" + key.upper()] = canonical(value)
        self.env["BASE_BRANCH"] = self.ctx["inputs"].get("base_branch", "main")
        self.env["ARCHON_NODE_EXECUTION"] = json.dumps(self.execution())
        self.env["TYPED_ARTIFACTS_FILE"] = str(owner.listing(self.entry["prefix"]))

    def execution(self):
        return {
            "path": self.sid,
            "invocation": {"loopPath": []},
            "attempt": {
                "checkoutStart": {"kind": "git", "commit": git(self.repo, "rev-parse", "HEAD")}
            },
        }

    def result(self, node):
        return self.owner.result(self.entry["prefix"] + node)

    def bindings(self, node):
        return {
            k: self.owner.resolve(v, self.entry["prefix"], self.ctx["inputs"])
            for k, v in node.get("with", {}).items()
        }

    def agent(self, node, sid):
        if not self.fixture:
            # Inline source prompts also receive the advisory contract.
            node = (
                {**node, "mutates_checkout": False} if self.owner.name == "issue-response" else node
            )
            result = super().agent(node, sid)
        else:
            spec = self.ctx["fixture"]
            if sid in spec.get("fail", []):
                raise RuntimeError("Fixture injected failure: " + sid)
            value = spec["agents"][sid]
            result = json.loads(json.dumps(value).replace("$RUN_ID", self.root.name))
            for relative, text in spec.get("artifacts", {}).get(sid, {}).items():
                path = self.root / relative
                if not path.resolve().is_relative_to(self.root):
                    raise ValueError("Fixture artifact escapes run")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        if node["id"] in LENSES and self.name == "review":
            report = self.root / "review" / f"{node['id']}.md"
            if not report.is_file() or not report.stat().st_size:
                raise ValueError("Selected reviewer did not write its report")
        return result

    def script(self, relative, bindings=None, **kwargs):
        # Re-sample each executable node, not a stale PR-creation commit.
        self.env["ARCHON_NODE_EXECUTION"] = json.dumps(self.execution())
        return super().script(relative, bindings, **kwargs)


class Composed(Run):
    def __init__(self, root):
        super().__init__(root, sources=ROOTS)
        self.graph = source_graph(self.name)

    def result(self, node):
        return load(self.root / "nodes" / (node + ".json"))

    def ref(self, node, fields, prefix=""):
        value = self.result(prefix + node)
        for key in fields.strip(".").split(".") if fields else []:
            if value is None:
                return None
            value = value[key]
        return value

    def resolve(self, value, prefix, inputs):
        if isinstance(value, dict) and "from" in value:
            return self.resolve(value["from"], prefix, inputs)
        if not isinstance(value, str):
            return value
        if value.startswith("$INPUTS.") and re.fullmatch(r"\$INPUTS\.[\w]+", value):
            return inputs[value[8:]]
        match = REF.fullmatch(value)
        if match:
            return self.ref(match[1], match[2], prefix)
        values = {
            "$ARTIFACTS_DIR": str(self.root),
            **{"$INPUTS." + k: canonical(v) for k, v in inputs.items()},
        }

        def substitute(m):
            token = m[0]
            if token in values:
                return values[token]
            ref = REF.fullmatch(token)
            return canonical(self.ref(ref[1], ref[2], prefix))

        return re.sub(
            r"\$ARTIFACTS_DIR|\$INPUTS\.[\w]+|\$[\w-]+\.output(?:\.[\w-]+)*", substitute, value
        )

    def inputs_for(self, entry):
        inputs = {**self.ctx["inputs"], "work_order": self.ctx["inputs"]["work"]}
        if entry["parent"]:
            parent = self.graph[entry["parent"]]
            inherited = self.inputs_for(parent)
            path = self.graph[parent["node"]["child_return"]]["source"]
            doc = yaml.safe_load((SOURCE / path).read_text())
            inputs.update({k: v.get("default", "") for k, v in doc.get("inputs", {}).items()})
            inputs.update(
                {
                    k: self.resolve(v, parent["prefix"], inherited)
                    for k, v in parent["node"].get("with", {}).items()
                }
            )
        return inputs

    def enabled(self, entry):
        if entry["parent"] and not self.enabled(self.graph[entry["parent"]]):
            return False
        condition = entry["node"].get("when")
        return not condition or when(condition, lambda n, f: self.ref(n, f, entry["prefix"]))

    def listing(self, prefix):
        rows = []
        for sid, entry in self.graph.items():
            if entry["prefix"] != prefix or entry["node"].get("output_type") != "review-lens":
                continue
            if load(self.root / "status" / (sid + ".json"), {}).get("status") != "succeeded":
                continue
            rows.append(
                {
                    "path": "nodes/" + sid + ".json",
                    "nodeId": entry["node"]["id"],
                    "producer": {"execution": {"path": sid, "invocation": {"loopPath": []}}},
                    "loopGroupPath": [],
                }
            )
        path = self.root / "typed" / ((prefix or "root") + ".json")
        save(path, {"artifactsByType": {"review-lens": rows}, "errors": []})
        return path

    def stage(self, sid, approved=False):
        if sid in ("approval_snapshot", "post") and self.name == "issue-response":
            return self.response_stage(sid, approved)
        entry = self.graph[sid]
        node = entry["node"]
        with lock(self.root / "locks" / (sid + ".lock")):
            path = self.root / "nodes" / (sid + ".json")
            if path.exists():
                return self.result(sid)
            if (self.root / "report.json").exists():
                raise ValueError("Terminal run; use a new state directory")
            for dep in entry["depends"]:
                if not (self.root / "nodes" / (dep + ".json")).exists():
                    raise ValueError("Missing prerequisite: " + dep)
            if not self.enabled(entry):
                save(path, None)
                save(self.root / "status" / (sid + ".json"), {"status": "skipped"})
                return None
            journal = self.root / "journal" / (sid + ".started")
            if journal.exists():
                raise ValueError("Uncertain attempt; reconcile before retrying " + sid)
            save(journal, {"stage": sid})
            stage = Stage(self, sid)
            try:
                if entry["kind"] == "include":
                    value = self.result(node["child_return"])
                elif entry["kind"] == "delivery":
                    value = self.delivery(stage, node)
                elif node.get("command") or node.get("prompt"):
                    value = stage.agent(node, sid)
                    if self.name == "review" and sid == "synthesize":
                        gaps = [
                            lens
                            for lens in LENSES
                            if self.enabled(self.graph[lens])
                            and load(self.root / "status" / (lens + ".json"), {}).get("status")
                            != "succeeded"
                        ]
                        if gaps:
                            value = {
                                **value,
                                "ready": False,
                                "action": "correct",
                                "findings_summary": value["findings_summary"]
                                + " Missing review coverage: "
                                + ", ".join(gaps),
                                "contract_left": [
                                    *value["contract_left"],
                                    "Missing review coverage: " + ", ".join(gaps),
                                ],
                            }
                elif node.get("script"):
                    script = node["script"]
                    if "\n" in script:
                        inline = self.root / "inline" / (sid + ".ts")
                        inline.parent.mkdir(exist_ok=True)
                        inline.write_text(script)
                        relative = str(inline)
                    else:
                        relative = str(
                            (SOURCE / entry["source"]).parent / "scripts" / (script + ".ts")
                        )
                    bindings = stage.bindings(node)
                    if self.fixture and node["id"] == "forge":
                        value = {"source": "gh"}
                    elif self.fixture and self.name == "pr" and sid == "publish":
                        value = self.fixture_publish(stage, bindings)
                    else:
                        if self.fixture and stage.name == "triage":
                            bindings["publish"] = "false"
                        if self.fixture and self.name == "review" and sid == "publish":
                            bindings.update(pr=None, scope="")
                        value = stage.script(
                            relative,
                            bindings,
                            timeout=node.get("timeout", 120000) / 1000,
                            raw=not bool(node.get("output_format")),
                        )
                elif node.get("bash"):
                    if node["id"] == "review-dir":
                        (self.root / "review").mkdir(exist_ok=True)
                    elif node["id"] != "review-complete":
                        raise ValueError("Unsupported source shell node")
                    value = ""
                else:
                    raise ValueError("Unsupported source node: " + sid)
                if value is not None and node.get("output_format"):
                    stage.check(value, node)
                save(path, value)
                save(self.root / "status" / (sid + ".json"), {"status": "succeeded"})
                return value
            except Exception as error:
                save(
                    self.root / "status" / (sid + ".json"),
                    {"status": "failed", "error": str(error)},
                )
                if self.name == "review" and sid in LENSES:
                    save(path, None)
                    return None
                raise

    def fixture_publish(self, stage, bindings):
        effect = self.ctx["fixture"].get("publication", "created")
        save(
            self.root / "effects/pr.json", {"simulated": True, "intent": bindings, "effect": effect}
        )
        if effect in ("failed", "uncertain"):
            if effect == "uncertain":
                save(
                    self.root / "effects/pr-uncertain.json",
                    {"message": "Creation may have landed; reconcile before retry"},
                )
            raise RuntimeError("Simulated publication " + effect)
        return self.ctx["fixture"]["publish"]

    def delivery(self, stage, node):
        request = {
            "inputs": stage.bindings(node),
            "root": str(self.root),
            "repo": str(self.repo),
            "mode": self.ctx["mode"],
            "config": self.config,
            "fixture": self.ctx.get("fixture"),
        }
        save(self.root / "delivery-request.json", request)
        invoke(
            [sys.executable, "-m", "archon_dagu.composed", "delivery-worker"],
            BASE,
            {**stage.env, "STATE_DIR": str(self.root)},
            timeout=self.config.get("delivery_timeout_seconds", 86400),
        )
        return load(self.root / "delivery/report.json")

    def response_stage(self, sid, approved):
        with lock(self.root / "locks" / (sid + ".lock")):
            if (self.root / "nodes" / (sid + ".json")).exists():
                return self.result(sid)
            if self.result("classify")["route"] == "skip":
                save(self.root / "nodes" / (sid + ".json"), None)
                return None
            if sid == "approval_snapshot":
                record = {
                    "repository": self.ctx["inputs"]["repository"],
                    "issue_number": int(self.ctx["inputs"]["issue_number"]),
                    "comment": self.result("investigate")["comment"],
                }
                save(self.root / "approval.json", record)
                save(
                    self.root / "approval-digest.json",
                    hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(),
                )
                value = record
            else:
                self.verify_approval()
                decision = (
                    self.ctx["fixture"].get("decision", "approve")
                    if self.fixture
                    else "approve"
                    if approved
                    else None
                )
                if decision not in ("approve", "reject"):
                    raise ValueError("Publication requires explicit approval")
                if decision == "reject":
                    value = {"posted": False, "decision": "reject"}
                else:
                    marker = self.root / "journal/post.started"
                    if marker.exists():
                        raise ValueError("Posting outcome uncertain; reconcile before retry")
                    save(marker, {"target": load(self.root / "approval.json")})
                    record = load(self.root / "approval.json")
                    if not self.fixture:
                        invoke(
                            [
                                "gh",
                                "issue",
                                "comment",
                                str(record["issue_number"]),
                                "--repo",
                                record["repository"],
                                "--body",
                                record["comment"],
                            ],
                            self.repo,
                            self.env,
                            timeout=120,
                        )
                    save(self.root / "effects/comment.json", {"simulated": self.fixture, **record})
                    value = {"posted": True, "decision": "approve"}
            save(self.root / "nodes" / (sid + ".json"), value)
            return value

    def verify_approval(self):
        record = load(self.root / "approval.json")
        expected = load(self.root / "approval-digest.json")
        if (
            not record
            or hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest() != expected
        ):
            raise ValueError("Approved target/draft changed")
        current = {
            "repository": self.ctx["inputs"]["repository"],
            "issue_number": int(self.ctx["inputs"]["issue_number"]),
            "comment": self.result("investigate")["comment"],
        }
        if record != current:
            raise ValueError("Draft or target changed after snapshot")

    def cleanup(self):
        for sid, entry in self.graph.items():
            if entry["node"].get("script") == "prune-scratch":
                stage = Stage(self, sid)
                stage.script(
                    str((SOURCE / entry["source"]).parent / "scripts/prune-scratch.ts"),
                    stage.bindings(entry["node"]),
                    raw=True,
                )

    def report(self, failed=False):
        old = load(self.root / "report.json")
        if old and not failed:
            return old
        self.cleanup()
        if self.name == "issue-response":
            post = self.result("post")
            skip = self.result("classify") and self.result("classify")["route"] == "skip"
            result = {
                "posted": bool(post and post["posted"]),
                "decision": "skip" if skip else post["decision"] if post else "pending",
            }
            outcome = result["posted"]
            needs = False
        else:
            result = self.result(self.doc["returns"])
            if failed and self.name == "ship":
                stage = Stage(self, "report")
                result = stage.script(str(SOURCE / "ship/scripts/report.ts"), {"outcome": None})
            field = self.doc.get("outcome_field")
            outcome = result.get(field, True) if isinstance(result, dict) else False
            needs = bool(
                isinstance(result, dict)
                and (
                    result.get("action") in ("ask", "replan")
                    or result.get("reason") in ("blocked", "needs_contract", "not_rooted", "ask")
                )
            )
        if not failed and isinstance(result, dict):
            if self.name == "ship":
                needs = not result["delivered"] and result["reason"] not in (
                    "no_action",
                    "refuted",
                    "failed",
                    "pr_create_unresolved",
                )
            elif self.name == "upkeep":
                needs = (
                    not result["delivered"]
                    and (self.result("assess") or {}).get("action") == "update"
                    and not load(self.root / "delivery-failed.json")
                )
        report = {
            "workflow": self.name,
            "mode": self.ctx["mode"],
            "lifecycle": "failed" if failed else "completed",
            "outcome": False if failed else outcome,
            "result": result,
            "needs_decision": needs,
            "external_effects": "simulated" if self.fixture else "live; experimental",
            "checkout": str(self.repo),
            "source_commit": json.loads((BASE / "COMPOSED_SOURCE.json").read_text())["commit"],
        }
        save(self.root / "report.json", report)
        return report


def delivery_worker(root):
    request = load(root / "delivery-request.json")
    inputs = request["inputs"]
    config = json.loads((BASE / "config/commands.json").read_text())
    config["agent_argv"] = request["config"]["agent_argv"]
    config.update(request["config"].get("delivery", {}))
    save(root / "delivery-commands.json", config)
    save(
        root / "delivery-fixture.json",
        {"rounds": (request["fixture"] or {}).get("delivery_rounds", [{}])},
    )
    os.environ.update(
        {
            "PORT_MODE": "dry" if request["mode"] == "fixture" else "real",
            "TARGET_REPO": request["repo"],
            "FIXTURE": str(root / "delivery-fixture.json"),
            "STAGE_COMMANDS": str(root / "delivery-commands.json"),
            "WORK": inputs["work"],
            "ERRORS": canonical(inputs.get("errors", "auto")),
            "PART": canonical(inputs.get("part", "")),
            "PULL_REQUEST": canonical(inputs.get("pull_request", "")),
            "BRANCH": canonical(inputs.get("branch", "")),
        }
    )
    path = root / "delivery"
    try:
        engine.initialize(path)
        for _ in range(4):
            if load(path / "state.json")["done"]:
                break
            for stage in engine.STAGES:
                engine.stage(path, stage)
        engine.finalize(path)
    except Exception:
        engine.finalize(path, True)
        save(root / "delivery-failed.json", True)


def setup(root):
    env = os.environ
    spec = None
    if env["STANDALONE_MODE"] == "fixture":
        path = pathlib.Path(env["STANDALONE_FIXTURE"])
        if not path.is_absolute():
            path = BASE / path
        spec = json.loads(path.read_text())
        env = {
            **env,
            **{"COMPOSED_" + k.upper(): str(v) for k, v in spec.get("parameters", {}).items()},
        }
    extra = {
        key: env.get("COMPOSED_" + key.upper(), default)
        for key, default in [
            ("light", "false"),
            ("part", ""),
            ("errors", "auto"),
            ("pull_request", ""),
            ("branch", ""),
            ("draft", "true"),
            ("publish_description", "false"),
            ("base_branch", "main"),
            ("repository", ""),
            ("issue_number", ""),
        ]
    }
    if env["STANDALONE_WORKFLOW"] == "issue-response":
        if (
            not re.fullmatch(r"[\w.-]+/[\w.-]+", extra["repository"])
            or not extra["issue_number"].isdigit()
            or int(extra["issue_number"]) < 1
        ):
            raise ValueError(
                "Issue response requires a qualified repository and positive issue_number"
            )
    if env["STANDALONE_MODE"] == "live" and env["STANDALONE_WORKFLOW"] in ("pr", "review"):
        branch = git(env["TARGET_REPO"], "branch", "--show-current")
        if env["STANDALONE_WORKFLOW"] == "pr" and not extra["branch"]:
            extra["branch"] = branch
        if env["STANDALONE_WORKFLOW"] == "review" and not env.get("SCOPE"):
            env = {**env, "SCOPE": branch}
    extra["prior_report"] = env.get("PRIOR_REPORT", "")
    if spec and spec.get("prior_review"):
        extra["prior_report"] = str(pathlib.Path(root).resolve() / "prior/report.md")
    initialize(
        root,
        env,
        sources=ROOTS,
        extra_inputs=extra,
        mutating=("ship", "upkeep"),
        require_work=("ship", "upkeep"),
    )

    if spec and spec.get("prior_review"):
        path = pathlib.Path(root) / "prior"
        path.mkdir(exist_ok=True)
        (path / "report.md").write_text("# Prior review\nFixture prior findings.\n")
        if spec["prior_review"] != "missing-prior-cursor":
            checkout = load(pathlib.Path(root) / "context.json")["checkout"]
            (path / "reviewed-head").write_text(git(checkout, "rev-parse", "HEAD") + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["init", "stage", "report", "failure", "verify-approval", "delivery-worker"],
    )
    parser.add_argument("stage", nargs="?")
    parser.add_argument("--approved", action="store_true")
    args = parser.parse_args()
    root = pathlib.Path(os.environ["STATE_DIR"]).resolve()
    if args.action == "init":
        setup(root)
        return
    if args.action == "delivery-worker":
        delivery_worker(root)
        return
    run = Composed(root)
    if args.action == "stage":
        run.stage(args.stage, args.approved)
        if args.stage == "approval_snapshot":
            print("true" if run.result("approval_snapshot") else "false")
    elif args.action == "verify-approval":
        run.verify_approval()
    else:
        report = run.report(args.action == "failure")
        print(str(report["needs_decision"]).lower())
        if not args.action == "failure" and load(root / "delivery-failed.json"):
            raise RuntimeError("Delivery failed; original terminal report retained")


if __name__ == "__main__":
    main()
