#!/usr/bin/env python3
import hashlib
import json
import pathlib
import shlex

import yaml

B = pathlib.Path(__file__).resolve().parents[1]
S = B / "vendor/archon/.archon/workflows/sdlc"
block = yaml.safe_load((S / "deliver/archon-deliver-block.yaml").read_text())
body = next(n for n in block["nodes"] if n["id"] == "rounds")["loop_group"]["nodes"]
manifest = {
    "repository": "coleam00/Archon",
    "commit": "72817c50dc51bb91773f71e5448bb7d387bfc8dd",
    "scope": "archon-deliver-block plus a minimal DAGU attention wrapper",
    "rounds": 4,
    "inputs": list(block["inputs"]),
    "mapping": [],
}
for n in body:
    manifest["mapping"].append(
        {
            "archon_node": n["id"],
            "kind": next((k for k in ["include", "command", "script"] if k in n), None),
            "target": next((n[k] for k in ["include", "command", "script"] if k in n), None),
            "depends_on": n.get("depends_on", []),
            "when": n.get("when"),
            "trigger_rule": n.get("trigger_rule", "all_success"),
        }
    )
manifest["hashes"] = {
    str(p.relative_to(S)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(S.rglob("*"), key=lambda path: path.relative_to(S).as_posix())
    if p.is_file()
}
existing = B / "SOURCE.json"
if existing.exists():
    pinned = json.loads(existing.read_text())
    if pinned["commit"] != manifest["commit"] or pinned["hashes"] != manifest["hashes"]:
        raise SystemExit("Vendored source differs from the pin; do not regenerate its provenance")
(B / "SOURCE.json").write_text(json.dumps(manifest, indent=2) + "\n")
# Preserve exact upstream prompts; developer explanations live separately.
prompt_map = {
    "implement": "implement/commands/implement.md",
    "pr": "pr/commands/pr.md",
    "scope": "review/commands/review-scope.md",
    "route": "review/commands/route-review.md",
    "seams": "review/commands/review-seams.md",
    "code": "review/commands/review-code.md",
    "tests": "review/commands/review-tests.md",
    "errors": "review/commands/review-errors.md",
    "docs": "review/commands/review-docs.md",
    "review": "review/commands/review-synthesize.md",
    "simplify": "simplify/commands/simplify.md",
    "settle-threads": "deliver/commands/settle-threads.md",
    "ci": "deliver/commands/ci.md",
    "update-pr-body": "deliver/commands/update-pr-body.md",
}
for stage, path in prompt_map.items():
    (B / "prompts" / f"{stage}.md").write_text((S / path).read_text())
(B / "prompts/reshape.md").write_text(
    next(n for n in body if n["id"] == "reshape")["with"]["work"] + "\n"
)
(B / "prompts/rereview.md").write_text((B / "prompts/review.md").read_text())
(B / "prompts/implement-delivery-context.md").write_text(
    next(n for n in body if n["id"] == "implement")["with"]["work"] + "\n"
)
# Persist exact source schemas where available; bridge validation additionally checks control fields.
schemas = {}
for folder, file, nodeid, key in [
    ("implement", "archon-implement.yaml", "implement", "implement"),
    ("pr", "archon-pr.yaml", "publish", "pr"),
    ("review", "archon-review-block.yaml", "result", "review"),
    ("simplify", "archon-simplify.yaml", "simplify", "simplify"),
]:
    d = yaml.safe_load((S / folder / file).read_text())
    node = next(n for n in d["nodes"] if n["id"] == nodeid)
    schemas[key] = node.get("output_format")
for n in body:
    if "output_format" in n:
        schemas[n["id"]] = n["output_format"]
(B / "schemas.json").write_text(json.dumps(schemas, indent=2) + "\n")


def cmd(args):
    return shlex.join(["python", "-m", "archon_dagu.engine", *args.split()])


params = [
    {"name": k, "type": "string", **({"default": v} if v is not None else {})}
    for k, v in [
        ("project_dir", None),
        ("state_dir", None),
        ("repo", ""),
        ("fixture", ""),  # Only explicit test transports consume a fixture.
        ("commands", "config/commands.json"),
        ("work", ""),
        ("pull_request", ""),
        ("branch", ""),
        ("part", ""),
        ("errors", "auto"),
    ]
]


def env(mode):
    return dict(
        PORT_MODE=mode,
        STATE_DIR="${params.state_dir}",
        TARGET_REPO="${params.repo}",
        FIXTURE="${params.fixture}",
        STAGE_COMMANDS="${params.commands}",
        WORK="${params.work}",
        PULL_REQUEST="${params.pull_request}",
        BRANCH="${params.branch}",
        PART="${params.part}",
        ERRORS="${params.errors}",
    )


def write(name, d):
    (B / "workflows" / name).write_text(yaml.safe_dump(d, sort_keys=False))


for shape in ["simple", "detailed"]:
    mode = "real"
    steps = [
        dict(id="check_setup", run=cmd("preflight")),
        dict(id="start_batch", depends=["check_setup"], run=cmd("init")),
    ]
    prev = "start_batch"
    if shape == "simple":
        steps.append(dict(id="fix_review_check_loop", depends=[prev], run=cmd("batch")))
        prev = "fix_review_check_loop"
    else:
        for n in range(1, 5):
            sid = f"round_{n}"
            steps.append(
                dict(
                    id=sid,
                    depends=[prev],
                    action="dag.run",
                    **{
                        "with": dict(
                            dag="archon-round",
                            params={
                                "state_dir": "${params.state_dir}",
                                "project_dir": "${params.project_dir}",
                            },
                        )
                    },
                )
            )
            prev = sid
    steps.extend(
        [
            dict(id="update_description_and_report", depends=[prev], run=cmd("finalize")),
            dict(
                id="read_ready_flag",
                depends=["update_description_and_report"],
                run=cmd("ready"),
                output="READY",
            ),
        ]
    )
    steps.append(
        dict(
            id="needs_your_input",
            depends=["read_ready_flag"],
            preconditions=[dict(condition="${READY}", expected="false")],
            action="human.task",
            **{
                "with": dict(
                    prompt="Archon delivery stopped not ready. Read report.json. Complete to leave this result, or request changes to run another capped batch. Merge remains outside this workflow.",
                    form=dict(type="object", properties={"note": {"type": "string"}}),
                    push_back=dict(
                        rewind_to="start_batch",
                        form=dict(
                            type="object",
                            properties={"FEEDBACK": {"type": "string"}},
                            required=["FEEDBACK"],
                        ),
                    ),
                )
            },
        )
    )
    write(
        f"{shape}-{mode}.yaml",
        dict(
            type="graph",
            working_dir="${params.project_dir}",
            description=f"Archon delivery: {shape} orchestration, {mode} effects; never merges.",
            params=params,
            env=env(mode),
            handler_on={"failure": {"run": cmd("failure")}},
            steps=steps,
        ),
    )
steps = []
for s in ["implement", "pr", "scope", "route"]:
    steps.append(
        dict(id=s, run=cmd("stage " + s), **({"depends": [steps[-1]["id"]]} if steps else {}))
    )
for s in ["seams", "code", "tests", "errors", "docs"]:
    steps.append(dict(id=s, depends=["route"], run=cmd("stage " + s)))
prev = ["seams", "code", "tests", "errors", "docs"]
for s in [
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
]:
    sid = s.replace("-", "_")
    steps.append(dict(id=sid, depends=prev, run=cmd("stage " + s)))
    prev = [sid]
write(
    "archon-round.yaml",
    dict(
        type="graph",
        working_dir="${params.project_dir}",
        params=[dict(name="state_dir", type="string"), dict(name="project_dir", type="string")],
        env=dict(STATE_DIR="${params.state_dir}"),
        steps=steps,
    ),
)
print("2 live delivery entrypoints and shared round DAG generated from pinned source")
stages = [
    "forge",
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
    "update-pr-body",
]
config = {
    "description": "Experimental live integration: pinned Archon scripts and configured fresh agent CLI; no merge",
    "requires": ["bun", "archon", "gh", "opencode"],
    "agent_argv": ["python", "-m", "archon_dagu.opencode"],
    "archon_argv": ["archon"],
    "commands": {s: ["python", "-m", "archon_dagu.live_stage"] for s in stages},
}
(B / "config/commands.json").write_text(json.dumps(config, indent=2) + "\n")
