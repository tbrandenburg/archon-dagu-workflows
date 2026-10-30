import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

from archon_dagu import engine

BASE = pathlib.Path(__file__).resolve().parents[1]
SOURCE = engine.SOURCE


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def run_stage(
    root,
    repo,
    agent,
    stage,
    round_number,
    outputs=None,
    previous=None,
    env_extra=None,
    work="accepted test work",
    feedback="",
):
    request = {
        "stage": stage,
        "round": round_number,
        "context": {
            "repo": str(repo),
            "command_config": {"agent_argv": [sys.executable, str(agent)]},
            "work": work,
            "pull_request": "",
            "branch": "test-branch",
            "part": None,
            "errors": "auto",
            "feedback": feedback,
        },
        "previous": previous or {},
        "outputs": outputs or {},
        "prompt_file": str(BASE / "prompts" / f"{stage}.md"),
        "source_root": str(SOURCE),
        "artifacts_dir": str(root),
        "fixture": {},
    }
    env = {
        **os.environ,
        **(env_extra or {}),
        "PATH": str(BASE / ".tools/bin") + os.pathsep + os.environ["PATH"],
        "PYTHONPATH": str(BASE / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "FAKE_AGENT_LOG": str(root / "agent-log.jsonl"),
    }
    return subprocess.run(
        [sys.executable, "-m", "archon_dagu.live_stage"],
        input=json.dumps(request),
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )


@pytest.fixture
def controlled_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Controlled Test"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("baseline\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)

    root = tmp_path / "artifacts"
    (root / "review").mkdir(parents=True)
    (root / "forge.json").write_text('{"source":"gh"}')
    commit = git(repo, "rev-parse", "HEAD")
    (root / "review/report.md").write_text("Prior review report.\n")
    (root / "review/reviewed-head").write_text(commit + "\n")
    agent = tmp_path / "fake_agent.py"
    agent.write_text(
        """import json, os, pathlib, sys
prompt = sys.stdin.read()
root = pathlib.Path(os.environ["ARTIFACTS_DIR"])
entry = {"prompt": prompt, "execution": json.loads(os.environ["ARCHON_NODE_EXECUTION"])}
with open(os.environ["FAKE_AGENT_LOG"], "a") as stream:
    stream.write(json.dumps(entry) + "\\n")
if prompt.startswith("# Review Scope"):
    (root / "review/scope.md").write_text("Controlled scope.\\n")
    result = {"head_matches": True, "pr": None, "report": {"type": "archon_artifact", "run_id": root.name, "path": "review/scope.md"}}
elif prompt.startswith("# Pick the review lenses"):
    result = {"seams": True, "code": True, "tests": True, "errors": False, "docs": False, "reason": "controlled route"}
elif prompt.startswith("# Decide the Review"):
    listing_path = pathlib.Path(os.environ["TYPED_ARTIFACTS_FILE"])
    listing = json.loads(listing_path.read_text())
    (root / "synthesis-observed.json").write_text(json.dumps({"path": str(listing_path), "listing": listing, "execution": entry["execution"], "prompt": prompt}))
    report = root / "review/report.md"
    report.write_text("Controlled synthesis report.\\n")
    (root / "review/report-round-2.md").write_text(report.read_text())
    if (root / "review/code.md").is_file():
        (root / "review/code-round-2.md").write_text((root / "review/code.md").read_text())
    result = {"ready": True, "action": "none", "findings_summary": "Controlled synthesis", "report": {"type": "archon_artifact", "run_id": root.name, "path": "review/report.md"}, "discoveries": [], "contract_left": []}
else:
    if os.environ.get("FAKE_CODE_REPORT", "true") == "true":
        (root / "review/code.md").write_text("Current controlled code review.\\n")
    result = {"completed": os.environ.get("FAKE_CODE_COMPLETED", "true") == "true", "findings": []}
print(json.dumps(result))
"""
    )
    return root, repo, agent, commit


def read_agent_log(root):
    return [json.loads(line) for line in (root / "agent-log.jsonl").read_text().splitlines()]


def test_live_full_review_route_and_light_rereview_typed_evidence(controlled_run):
    root, repo, agent, commit = controlled_run
    scope = run_stage(root, repo, agent, "scope", 1)
    assert scope.returncode == 0, scope.stderr
    route = run_stage(root, repo, agent, "route", 1)
    assert route.returncode == 0, route.stderr
    route_output = json.loads(route.stdout)
    for lens in ["seams", "code", "tests"]:
        engine.save(root / f"round-1/{lens}.json", {"completed": True, "findings": []})
        (root / f"review/{lens}.md").write_text(f"Current {lens} report.\\n")
    engine.save(root / "state.json", {"round": 0})
    engine.typed_listing(root)
    full = run_stage(root, repo, agent, "review", 1, {"route": route_output})
    assert full.returncode == 0, full.stderr
    full_observation = json.loads((root / "synthesis-observed.json").read_text())
    full_context = json.loads(
        full_observation["prompt"]
        .split("DAGU stage context (authoritative bound inputs):\n", 1)[1]
        .split("\nReturn exactly one", 1)[0]
    )
    assert full_context["current_outputs"]["route"] == route_output
    assert full_observation["execution"]["path"] == "review.synthesize"

    (root / "review/reviewed-head").write_text(commit + "\n")
    rereview = run_stage(
        root,
        repo,
        agent,
        "rereview",
        2,
        {"route": route_output},
        {"prior_report": "round-1/review.json", "light_review": True},
    )
    assert rereview.returncode == 0, rereview.stderr
    mode = json.loads((root / "mode-2.json").read_text())
    assert mode["execution"]["path"] == "rereview.mode"
    assert mode["execution"]["invocation"]["loopPath"] == [{"groupId": "rounds", "iteration": 2}]
    assert mode["execution"]["attempt"]["checkoutStart"]["commit"] == commit
    assert mode["light"] is True and mode["code"] is True
    assert not any(mode[key] for key in ["seams", "tests", "errors", "docs"])

    observed = json.loads((root / "synthesis-observed.json").read_text())
    prompt = observed["prompt"]
    assert "$mode.output" not in prompt
    assert '"light": true' in prompt
    assert observed["execution"]["path"] == "rereview.synthesize"
    code_agent = next(
        row for row in read_agent_log(root) if row["execution"]["path"] == "rereview.code"
    )
    assert code_agent["execution"]["attempt"]["checkoutStart"]["commit"] == commit
    context = json.loads(
        prompt.split("DAGU stage context (authoritative bound inputs):\n", 1)[1].split(
            "\nReturn exactly one", 1
        )[0]
    )
    assert context["current_outputs"]["route"] == {
        "seams": False,
        "code": True,
        "tests": False,
        "errors": False,
        "docs": False,
    }
    assert context["mode"]["execution"]["path"] == "rereview.mode"
    assert context["current_outputs"]["route"]["seams"] is False

    listing = observed["listing"]
    entries = listing["artifactsByType"]["review-lens"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["nodeId"] == "code"
    producer = entry["producer"]["execution"]
    assert producer["path"] == "rereview.code"
    assert producer["invocation"]["loopPath"] == mode["execution"]["invocation"]["loopPath"]
    assert producer["attempt"]["checkoutStart"]["commit"] == commit
    assert entry["path"] == "round-2/rereview-code.json"
    evidence_path = root / entry["path"]
    assert evidence_path.is_file() and json.loads(evidence_path.read_text())["completed"] is True
    assert (root / "review/code.md").read_text() == "Current controlled code review.\n"
    assert (root / "review/report-round-2.md").is_file()
    assert (root / "review/code-round-2.md").is_file()

    engine.save(root / "round-2/rereview.json", json.loads(rereview.stdout))
    engine.save(root / "state.json", {"round": 1})
    engine.typed_listing(root)
    rebuilt = json.loads((root / "typed-2.json").read_text())
    assert rebuilt["artifactsByType"]["review-lens"] == entries


def test_live_agent_receives_large_prompt_without_stdin_deadlock(controlled_run):
    root, repo, agent, _ = controlled_run
    work = "large-work-input-" + ("x" * 200_000)
    result = run_stage(root, repo, agent, "code", 1, feedback=work)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"completed": True, "findings": []}
    invocation = read_agent_log(root)[0]
    assert work in invocation["prompt"]
    assert len(invocation["prompt"]) > 200_000
    assert (root / "review/code.md").is_file()


def test_rereview_uses_one_aggregate_stage_deadline(controlled_run, tmp_path, monkeypatch):
    root, repo, _, commit = controlled_run
    monkeypatch.setenv("PATH", str(BASE / ".tools/bin") + os.pathsep + os.environ["PATH"])
    (root / "review/reviewed-head").write_text(commit + "\n")
    agent = tmp_path / "timed_agent.py"
    calls = root / "timed-agent-calls.jsonl"
    agent.write_text(
        "import json, os, pathlib, sys, time\n"
        "prompt = sys.stdin.read()\n"
        f"calls = pathlib.Path({str(calls)!r})\n"
        "with calls.open('a') as stream: stream.write(json.dumps({'time': time.monotonic(), 'pid': os.getpid(), 'prompt': prompt.splitlines()[0]}) + '\\n')\n"
        "time.sleep(2.0)\n"
        "if prompt.startswith('# Review Scope'):\n"
        " print(json.dumps({'head_matches': True, 'pr': None, 'report': {'type': 'archon_artifact', 'run_id': pathlib.Path(os.environ['ARTIFACTS_DIR']).name, 'path': 'review/scope.md'}}))\n"
        "elif prompt.startswith('# Decide the Review'):\n"
        " time.sleep(10)\n"
        " print(json.dumps({'ready': True, 'action': 'none', 'findings_summary': 'controlled', 'report': {'type': 'archon_artifact', 'run_id': pathlib.Path(os.environ['ARTIFACTS_DIR']).name, 'path': 'review/report.md'}, 'discoveries': [], 'contract_left': []}))\n"
        "else:\n"
        " (pathlib.Path(os.environ['ARTIFACTS_DIR']) / 'review/code.md').write_text('code lens\\n')\n"
        " print(json.dumps({'completed': True, 'findings': []}))\n"
    )
    engine.save(
        root / "context.json",
        {
            "mode": "real",
            "repo": str(repo),
            "work": "accepted controlled work",
            "pull_request": "",
            "branch": "test-branch",
            "part": None,
            "errors": "auto",
            "feedback": "",
            "command_config": {
                "commands": {"rereview": [sys.executable, "-m", "archon_dagu.live_stage"]},
                "stage_timeout_seconds": 6,
                "test_transport": True,
                "agent_argv": [sys.executable, str(agent)],
            },
        },
    )
    engine.save(root / "state.json", {"round": 1, "done": False, "light_review": True})
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="rereview command exceeded 6s"):
        engine.invoke(root, "rereview", {}, 2, {})
    elapsed = time.monotonic() - started

    entries = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [entry["prompt"] for entry in entries] == [
        "# Review Scope",
        "# Code Review — Correctness",
        "# Decide the Review",
    ]
    assert entries[1]["time"] - entries[0]["time"] >= 1.8
    assert entries[2]["time"] - entries[1]["time"] >= 1.8
    assert elapsed >= 5.8
    assert elapsed < 10
    for entry in entries:
        with pytest.raises(ProcessLookupError):
            os.kill(entry["pid"], 0)


@pytest.mark.parametrize(("completed", "write_report"), [("false", "true"), ("true", "false")])
def test_live_rereview_does_not_certify_incomplete_code(controlled_run, completed, write_report):
    root, repo, agent, _ = controlled_run
    (root / "review/code.md").write_text("stale prior-round code report\n")
    result = run_stage(
        root,
        repo,
        agent,
        "rereview",
        2,
        {},
        {"light_review": True},
        {"FAKE_CODE_COMPLETED": completed, "FAKE_CODE_REPORT": write_report},
    )
    assert result.returncode != 0
    assert "rereview-code.json" not in result.stdout
    assert not (root / "typed-2.json").exists()
    assert not (root / "round-2/rereview-code.json").exists()
