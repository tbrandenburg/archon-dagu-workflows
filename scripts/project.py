"""Shared implementation for Taskfile, Makefile, CI, and documented examples."""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import uuid

from archon_dagu.engine import BASE, SOURCE, STAGES

VARIANTS = ("simple-real", "detailed-real")


def command(*args, **kwargs):
    return subprocess.run(args, cwd=BASE, check=True, **kwargs)


def source_check():
    manifest = json.loads((BASE / "SOURCE.json").read_text())
    for path, expected in manifest["hashes"].items():
        actual = hashlib.sha256((SOURCE / path).read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"Pinned upstream source changed: {path}")
    print(f"Verified {len(manifest['hashes'])} pinned upstream files")


def generated_check():
    paths = [
        BASE / "SOURCE.json",
        BASE / "schemas.json",
        BASE / "config/commands.json",
    ]
    for folder, suffix in [("workflows", "*.yaml"), ("prompts", "*.md")]:
        paths.extend(sorted((BASE / folder).rglob(suffix)))
    before = {p: p.read_bytes() for p in paths}
    command(sys.executable, "scripts/generate.py")
    changed = [str(p.relative_to(BASE)) for p in paths if p.read_bytes() != before[p]]
    if changed:
        raise SystemExit("Generated files were stale: " + ", ".join(changed))
    print("Generated files are current and portable")


def dagu_binary():
    path = os.environ.get("DAGU") or str(BASE / ".tools/bin/dagu")
    if not pathlib.Path(path).is_file():
        path = shutil.which("dagu")
    if not path:
        raise SystemExit("DAGU missing. Run task tools or make tools.")
    return path


def native_checks():
    binary = dagu_binary()
    for file in sorted((BASE / "workflows").glob("*.yaml")):
        command(binary, "--dagu-home", str(BASE / ".runs/dagu"), "validate", str(file))
    for variant in VARIANTS:
        command(
            binary,
            "--dagu-home",
            str(BASE / ".runs/dagu"),
            "dry",
            str(BASE / "workflows" / (variant + ".yaml")),
            "--",
            f"project_dir={BASE}",
            f"state_dir={BASE / '.runs' / 'preview' / variant}",
        )


def example(variant, case, executor):
    print(
        "FIXTURE TEST: no agent/model or GitHub operation will run. "
        "Use make agent-smoke or make deliver for actual agents.",
        flush=True,
    )
    if variant not in VARIANTS:
        raise SystemExit("Select simple-real or detailed-real")
    fixture = BASE / "examples/fixtures" / (case + ".json")
    if not fixture.is_file():
        raise SystemExit(f"Unknown fixture: {case}")
    state = BASE / ".runs/examples" / f"{variant}-{case}-{uuid.uuid4().hex[:8]}"
    repo = state / "mock-checkout"
    repo.mkdir(parents=True)
    command("git", "init", "-q", str(repo))
    config = state / "test-commands.json"
    config.write_text(
        json.dumps(
            {
                "test_transport": True,
                "commands": {
                    s: [sys.executable, "-m", "archon_dagu.mock_stage"]
                    for s in ["forge", *STAGES[:-1], "update-pr-body"]
                },
            },
            indent=2,
        )
        + "\n"
    )
    params = {
        "project_dir": str(BASE),
        "state_dir": str(state),
        "fixture": str(fixture),
        "repo": str(repo),
        "commands": str(config),
        "work": "Accepted fixture work; external effects mocked",
    }
    if executor == "dagu" and case not in ("ready", "fix_ci", "simplify_then_rereview"):
        raise SystemExit(
            "Native examples support ready, fix_ci, simplify_then_rereview; "
            "not-ready cases reach a real human task. Use EXECUTOR=local for those."
        )
    if executor == "local":
        from archon_dagu.local_runner import run

        trace = run(BASE / "workflows" / (variant + ".yaml"), params)
        (state / "trace.json").write_text(json.dumps(trace, indent=2) + "\n")
    else:
        command(
            dagu_binary(),
            "--dagu-home",
            str(BASE / ".runs/dagu"),
            "start",
            str(BASE / "workflows" / (variant + ".yaml")),
            "--",
            *(f"{k}={v}" for k, v in params.items()),
        )
    report = json.loads((state / "report.json").read_text())
    expected = "round_cap" if case == "four_round_cap" else "delivered"
    if report["reason"] != expected or report["merged"] or not report["simulated"]:
        raise SystemExit(f"Unexpected outcome: {report}")
    print(json.dumps({"executor": executor, "report": report, "artifacts": str(state)}, indent=2))


def native_smoke():
    # CI must fail rather than quietly substitute the local harness.
    try:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.close()
    except OSError as error:
        raise SystemExit(f"Native DAGU execution unavailable on this host: {error}") from error
    for variant in VARIANTS:
        for case in ("ready", "fix_ci", "simplify_then_rereview"):
            example(variant, case, "dagu")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        choices=["source-check", "generated-check", "validate", "native-smoke", "demo", "clean"],
    )
    parser.add_argument("--variant", choices=VARIANTS, default="simple-real")
    parser.add_argument("--case", default="fix_ci")
    parser.add_argument("--executor", choices=["local", "dagu"], default="local")
    args = parser.parse_args()
    match args.target:
        case "source-check":
            source_check()
        case "generated-check":
            generated_check()
        case "validate":
            native_checks()
        case "native-smoke":
            native_smoke()
        case "demo":
            example(args.variant, args.case, args.executor)
        case "clean":
            worktrees = [p.parent for p in (BASE / ".runs").rglob(".git") if p.is_file()]
            if worktrees:
                raise SystemExit(
                    "Refusing to delete registered Git worktrees; remove them with git worktree remove first: "
                    + ", ".join(map(str, worktrees))
                )
            shutil.rmtree(BASE / ".runs", ignore_errors=True)


if __name__ == "__main__":
    main()
