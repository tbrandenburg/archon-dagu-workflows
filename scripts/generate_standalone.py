"""Generate the six standalone DAGs and preserve their source contracts."""

import hashlib
import json
import pathlib

import yaml

B = pathlib.Path(__file__).resolve().parents[1]
V = B / "vendor/archon"
S = V / ".archon/workflows/sdlc"
SOURCES = {
    "validate": "validate/archon-validate.yaml",
    "investigate": "investigate/archon-investigate.yaml",
    "plan": "plan/archon-plan-block.yaml",
    "triage": "triage/archon-triage-block.yaml",
    "implement": "implement/archon-implement.yaml",
    "standup": "../maintainer/maintainer-standup.yaml",
}


def generate():
    destination = B / "prompts/standalone"
    destination.mkdir(parents=True, exist_ok=True)
    workflows = {}
    for name, path in SOURCES.items():
        source = (S / path).resolve()
        doc = yaml.safe_load(source.read_text())
        nodes = doc["nodes"]
        mapping = []
        for node in nodes:
            command = node.get("command") or node.get("loop", {}).get("command")
            if command:
                prompt = (
                    V / ".archon/commands" if name == "standup" else source.parent / "commands"
                ) / (command + ".md")
                target = destination / f"{name}-{node['id']}.md"
                target.write_bytes(prompt.read_bytes())
            mapping.append(
                {
                    "source_node": node["id"],
                    "kind": next(k for k in ("command", "loop", "script", "bash") if k in node),
                    "prompt": f"prompts/standalone/{name}-{node['id']}.md" if command else None,
                }
            )
        workflows[name] = {"source": str(source.relative_to(V)), "mapping": mapping}
        for mode in ("fixture", "live"):
            steps = [{"id": "setup", "run": "python -m archon_dagu.standalone init"}]
            if name == "implement":
                for turn in range(1, 6):
                    steps.append(
                        {
                            "id": f"implement_{turn}",
                            "depends": [steps[-1]["id"]],
                            "run": f"python -m archon_dagu.standalone stage implement_{turn}",
                        }
                    )
            else:
                for node in nodes:
                    sid = node["id"].replace("-", "_")
                    deps = [x.replace("-", "_") for x in node.get("depends_on", [])] or ["setup"]
                    steps.append(
                        {
                            "id": sid,
                            "depends": deps,
                            "run": f"python -m archon_dagu.standalone stage {node['id']}",
                        }
                    )
            deps = [steps[-1]["id"]]
            steps.append(
                {
                    "id": "report",
                    "depends": deps,
                    "run": "python -m archon_dagu.standalone report",
                    "output": "NEEDS_DECISION",
                }
            )
            if mode == "live" and name != "standup" and name != "validate":
                steps.append(
                    {
                        "id": "decision",
                        "depends": ["report"],
                        "preconditions": [{"condition": "${NEEDS_DECISION}", "expected": "true"}],
                        "action": "human.task",
                        "with": {
                            "prompt": "Read ${params.state_dir}/report.json and the source report. This run needs an operator decision. Complete with your ruling, then start a new run with updated input; no changes or public writes happen on completion.",
                            "form": {
                                "type": "object",
                                "properties": {"ruling": {"type": "string", "minLength": 1}},
                                "required": ["ruling"],
                            },
                        },
                    }
                )
            params = [
                {
                    "name": k,
                    "type": "string",
                    **({"default": default} if default is not None else {}),
                }
                for k, default in [
                    ("project_dir", None),
                    ("state_dir", None),
                    ("repo", ""),
                    ("input", ""),
                    ("scope", ""),
                    ("prior_report", ""),
                    ("related", "[]"),
                    ("publish", "false"),
                    ("fixture", f"examples/standalone/{name}-happy.json"),
                    ("config", "config/standalone.json"),
                ]
            ]
            env = {
                "STANDALONE_WORKFLOW": name,
                "STANDALONE_MODE": mode,
                **{
                    k.upper(): "${params." + p + "}"
                    for k, p in [
                        ("state_dir", "state_dir"),
                        ("target_repo", "repo"),
                        ("work_input", "input"),
                        ("scope", "scope"),
                        ("prior_report", "prior_report"),
                        ("related", "related"),
                        ("publish", "publish"),
                        ("standalone_fixture", "fixture"),
                        ("standalone_config", "config"),
                    ]
                },
            }
            dag = {
                "type": "graph",
                "description": f"Archon {name}; {mode} transport. See docs/standalone.md.",
                "working_dir": "${params.project_dir}",
                "params": params,
                "env": env,
                "handler_on": {"failure": {"run": "python -m archon_dagu.standalone failure"}},
                "steps": steps,
            }
            (B / "workflows" / f"{name}-{mode}.yaml").write_text(
                yaml.safe_dump(dag, sort_keys=False)
            )
    extras = [p for p in (V / ".archon").rglob("*") if p.is_file() and S not in p.parents]
    manifest = {
        "repository": "coleam00/Archon",
        "commit": json.loads((B / "SOURCE.json").read_text())["commit"],
        "workflows": workflows,
        "extra_hashes": {
            p.relative_to(V).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(extras)
        },
    }
    pin = B / "STANDALONE_SOURCE.json"
    if pin.exists():
        old = json.loads(pin.read_text())
        if old["commit"] != manifest["commit"] or old["extra_hashes"] != manifest["extra_hashes"]:
            raise SystemExit("Standalone source pin changed; refusing to re-bless provenance")
    pin.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    generate()
