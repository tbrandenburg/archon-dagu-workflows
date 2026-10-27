"""Compile pinned Archon stage graphs into visible DAGU steps."""

import hashlib
import json
from pathlib import Path

import yaml

B = Path(__file__).resolve().parents[1]
V = B / "vendor/archon"
S = V / ".archon/workflows/sdlc"
ROOTS = {
    "review": "review/archon-review-block.yaml",
    "simplify": "simplify/archon-simplify.yaml",
    "pr": "pr/archon-pr.yaml",
    "ship": "ship/archon-ship-block.yaml",
    "upkeep": "upkeep/archon-upkeep.yaml",
    "issue-response": "../examples/proactive-issue-investigation.yaml",
}
BLOCKS = {
    "archon-triage-block": "triage/archon-triage-block.yaml",
    "archon-plan-block": "plan/archon-plan-block.yaml",
    "archon-investigate": "investigate/archon-investigate.yaml",
}


def compile_graph(workflow):
    graph = {}

    def visit(path, prefix="", parent=None, parent_deps=()):
        doc = yaml.safe_load((S / path).read_text())
        for original in doc["nodes"]:
            node = dict(original)
            sid = prefix + node["id"]
            deps = [prefix + x for x in node.get("depends_on", [])]
            if not deps:
                deps = list(parent_deps)
            kind = "node"
            include = node.get("include")
            if include in BLOCKS:
                kind = "include"
                visit(BLOCKS[include], sid + ".", sid, deps)
                child_doc = yaml.safe_load((S / BLOCKS[include]).read_text())
                deps = [sid + "." + n["id"] for n in child_doc["nodes"]]
                node["child_return"] = sid + "." + child_doc["returns"]
            elif include == "archon-deliver-block":
                kind = "delivery"
            graph[sid] = {
                "source": path,
                "prefix": prefix,
                "parent": parent,
                "depends": deps,
                "kind": kind,
                "node": node,
            }

    visit(ROOTS[workflow])
    return graph


def generate():
    destination = B / "prompts/composed"
    destination.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for name in ROOTS:
        graph = compile_graph(name)
        mapping[name] = graph
        for sid, entry in graph.items():
            node = entry["node"]
            prompt = node.get("prompt")
            if node.get("command"):
                prompt = (
                    (S / entry["source"])
                    .parent.joinpath("commands", node["command"] + ".md")
                    .read_text()
                )
            if prompt:
                source_name = (S / entry["source"]).parent.name
                if name == "issue-response":
                    source_name = name
                (destination / f"{source_name}-{node['id']}.md").write_text(prompt)
        for mode in ("fixture", "live"):
            steps = [{"id": "setup", "run": "python -m archon_dagu.composed init"}]
            for sid, entry in graph.items():
                if name == "issue-response" and sid in ("review", "drop", "post"):
                    continue
                step = {
                    "id": sid.replace(".", "__").replace("-", "_"),
                    "depends": [d.replace(".", "__").replace("-", "_") for d in entry["depends"]]
                    or ["setup"],
                    "run": f"python -m archon_dagu.composed stage {sid}",
                }
                steps.append(step)
            if name == "issue-response":
                steps.append(
                    {
                        "id": "approval_snapshot",
                        "depends": ["investigate"],
                        "run": "python -m archon_dagu.composed stage approval_snapshot",
                        "output": "NEEDS_APPROVAL",
                    }
                )
                if mode == "live":
                    steps.append(
                        {
                            "id": "approve_reply",
                            "depends": ["approval_snapshot"],
                            "preconditions": [
                                {"condition": "${NEEDS_APPROVAL}", "expected": "true"}
                            ],
                            "run": "python -m archon_dagu.composed verify-approval",
                            "approval": {
                                "prompt": "Review the exact reply and target in ${params.state_dir}/approval.json. Approve to post those bytes; Reject ends the run without posting."
                            },
                        }
                    )
                steps.append(
                    {
                        "id": "post_reply",
                        "depends": ["approve_reply" if mode == "live" else "approval_snapshot"],
                        "run": "python -m archon_dagu.composed stage post --approved",
                    }
                )
            steps.append(
                {
                    "id": "finish",
                    "depends": [s["id"] for s in steps[1:]],
                    "run": "python -m archon_dagu.composed report",
                    "output": "NEEDS_DECISION",
                }
            )
            # Live issue-response's success handler also reports a classifier skip,
            # where native DAGU skips approval and its dependent steps.
            handlers = {"failure": {"run": "python -m archon_dagu.composed failure"}}
            if name == "issue-response":
                handlers["success"] = {"run": "python -m archon_dagu.composed report"}
            if mode == "live" and name in ("review", "ship", "upkeep"):
                steps.append(
                    {
                        "id": "decision",
                        "depends": ["finish"],
                        "preconditions": [{"condition": "${NEEDS_DECISION}", "expected": "true"}],
                        "action": "human.task",
                        "with": {
                            "prompt": "Read ${params.state_dir}/report.json. Record your ruling, then start a new run with updated inputs. No merge is performed.",
                            "form": {
                                "type": "object",
                                "properties": {"ruling": {"type": "string", "minLength": 1}},
                                "required": ["ruling"],
                            },
                        },
                    }
                )
            params = [
                {"name": k, "type": "string", **({"default": v} if v is not None else {})}
                for k, v in [
                    ("project_dir", None),
                    ("state_dir", None),
                    ("repo", ""),
                    ("input", ""),
                    ("scope", ""),
                    ("prior_report", ""),
                    ("light", "false"),
                    ("part", ""),
                    ("errors", "auto"),
                    ("publish", "false"),
                    ("pull_request", ""),
                    ("branch", ""),
                    ("draft", "true"),
                    ("publish_description", "false"),
                    ("base_branch", "main"),
                    ("repository", ""),
                    ("issue_number", ""),
                    ("fixture", f"examples/composed/{name}-happy.json"),
                    ("config", "config/composed.json"),
                ]
            ]
            fields = {
                "STATE_DIR": "state_dir",
                "TARGET_REPO": "repo",
                "WORK_INPUT": "input",
                "SCOPE": "scope",
                "PRIOR_REPORT": "prior_report",
                "PUBLISH": "publish",
                "STANDALONE_FIXTURE": "fixture",
                "STANDALONE_CONFIG": "config",
                **{
                    "COMPOSED_" + k.upper(): k
                    for k in [
                        "light",
                        "part",
                        "errors",
                        "pull_request",
                        "branch",
                        "draft",
                        "publish_description",
                        "base_branch",
                        "repository",
                        "issue_number",
                    ]
                },
            }
            dag = {
                "type": "graph",
                "description": f"Source-backed Archon {name}; {mode}. See docs/composed.md.",
                "working_dir": "${params.project_dir}",
                "params": params,
                "env": {
                    "STANDALONE_WORKFLOW": name,
                    "STANDALONE_MODE": mode,
                    **{k: "${params." + v + "}" for k, v in fields.items()},
                },
                "handler_on": handlers,
                "steps": steps,
            }
            (B / "workflows" / f"{name}-{mode}.yaml").write_text(
                yaml.safe_dump(dag, sort_keys=False)
            )
    extra = ".archon/workflows/examples/proactive-issue-investigation.yaml"
    manifest = {
        "repository": "coleam00/Archon",
        "commit": json.loads((B / "SOURCE.json").read_text())["commit"],
        "graphs": mapping,
        "extra_hashes": {extra: hashlib.sha256((V / extra).read_bytes()).hexdigest()},
    }
    target = B / "COMPOSED_SOURCE.json"
    if (
        target.exists()
        and json.loads(target.read_text())["extra_hashes"] != manifest["extra_hashes"]
    ):
        raise SystemExit("Composed source hash changed; refusing to re-bless provenance")
    target.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    generate()
