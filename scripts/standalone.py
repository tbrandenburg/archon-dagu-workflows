"""Run standalone fixture examples through local commands or native DAGU."""

import argparse
import json
import os
import pathlib
import subprocess
import uuid

from project import dagu_binary

from archon_dagu.engine import BASE
from archon_dagu.local_runner import run
from archon_dagu.standalone import SOURCES


def example(workflow, case="happy", executor="local"):
    fixture = BASE / "examples/standalone" / f"{workflow}-{case}.json"
    spec = json.loads(fixture.read_text())
    root = BASE / ".runs/standalone" / f"{workflow}-{case}-{uuid.uuid4().hex[:8]}"
    dag = BASE / "workflows" / f"{workflow}-fixture.yaml"
    params = {
        "project_dir": str(BASE),
        "state_dir": str(root),
        "fixture": str(fixture),
        "config": os.environ.get("STANDALONE_FIXTURE_CONFIG", "config/standalone.json"),
    }
    failed = False
    try:
        if executor == "local":
            trace = run(dag, params)
            (root / "trace.json").write_text(json.dumps(trace, indent=2) + "\n")
        else:
            result = subprocess.run(
                [
                    dagu_binary(),
                    "--dagu-home",
                    str(BASE / ".runs/dagu"),
                    "start",
                    str(dag),
                    "--",
                    *(f"{k}={v}" for k, v in params.items()),
                ],
                cwd=BASE,
                env={
                    **os.environ,
                    "PATH": str(BASE / ".tools/bin") + os.pathsep + os.environ["PATH"],
                },
                capture_output=True,
                text=True,
            )
            root.mkdir(parents=True, exist_ok=True)
            (root / "dagu.log").write_text(result.stdout + result.stderr)
            failed = result.returncode != 0
    except RuntimeError as error:
        failed = True
        (root / "error.log").write_text(str(error))
    if not (root / "report.json").exists():
        raise AssertionError(f"No report from {workflow}/{case}; inspect {root}")
    report = json.loads((root / "report.json").read_text())
    expected = spec["expected"]
    if bool(expected.get("failure")) != failed or (report["lifecycle"] == "failed") != failed:
        raise AssertionError(f"Unexpected lifecycle {workflow}/{case}: {report}")
    if not failed:
        for key, value in expected.items():
            actual = report[key] if key in ("outcome", "reason") else report["result"][key]
            if actual != value:
                raise AssertionError(f"{workflow}/{case} {key}: {actual!r} != {value!r}")
    if workflow == "standup" and not failed:
        state = pathlib.Path(report["checkout"]) / ".archon/maintainer-standup/state.json"
        assert json.loads(state.read_text())["last_dev_sha"] == "fixture-head"
        if case == "prior-state":
            facts = json.loads((root / "nodes/read-context.json").read_text())
            assert facts["prior_state"] == spec["prior_state"]
    return {
        "workflow": workflow,
        "case": case,
        "executor": executor,
        "lifecycle": report["lifecycle"],
        "outcome": report["outcome"],
        "artifacts": str(root.relative_to(BASE)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=["demo", "scenarios", "validate"])
    parser.add_argument("--workflow", choices=SOURCES, default="investigate")
    parser.add_argument("--case", default="happy")
    parser.add_argument("--executor", choices=["local", "dagu"], default="local")
    args = parser.parse_args()
    if args.target == "validate":
        for workflow in SOURCES:
            for mode in ("fixture", "live"):
                dag = BASE / "workflows" / f"{workflow}-{mode}.yaml"
                params = [
                    "--",
                    f"project_dir={BASE}",
                    f"state_dir={BASE / '.runs/preview' / (workflow + '-' + mode)}",
                ]
                subprocess.run(
                    [
                        dagu_binary(),
                        "--dagu-home",
                        str(BASE / ".runs/dagu"),
                        "dry",
                        str(dag),
                        *params,
                    ],
                    check=True,
                    cwd=BASE,
                )
        return
    if args.target == "demo":
        print(json.dumps(example(args.workflow, args.case, args.executor), indent=2))
        return
    results = []
    for fixture in sorted((BASE / "examples/standalone").glob("*.json")):
        workflow = json.loads(fixture.read_text())["workflow"]
        case = fixture.stem[len(workflow) + 1 :]
        evidence = example(workflow, case, args.executor)
        results.append(evidence)
        print(f"{workflow}/{case}: {evidence['lifecycle']} (expected)", flush=True)
    path = BASE / ".runs" / f"standalone-{args.executor}.json"
    path.write_text(json.dumps(results, indent=2) + "\n")
    print(f"{len(results)} standalone scenarios verified via {args.executor}; evidence: {path}")


if __name__ == "__main__":
    main()
