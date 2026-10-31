"""Reproduce pinned Dagu/OpenCode contract gaps without providers or forge writes."""

import argparse
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import uuid

import yaml

from archon_dagu.engine import BASE, save
from archon_dagu.opencode import final_answer
from archon_dagu.standalone import Run

AGENT = BASE / "scripts/harness_probe_agent.py"
CASES = ("jsonl", "managed", "timeout", "signal")


def environment(root: pathlib.Path, case: str) -> dict[str, str]:
    """Do not inherit credentials, service discovery, hooks or operator configuration."""
    return {
        "PATH": os.pathsep.join(
            (str(root / "bin"), str(pathlib.Path(sys.executable).parent), "/usr/bin", "/bin")
        ),
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "home/config"),
        "XDG_DATA_HOME": str(root / "home/data"),
        "XDG_STATE_HOME": str(root / "home/state"),
        "XDG_CACHE_HOME": str(root / "home/cache"),
        "PROBE_ROOT": str(root),
        "PROBE_CASE": case,
    }


def prepare(root: pathlib.Path, env: dict[str, str]) -> tuple[Run, str]:
    """Render the real investigate prompt via Run.agent, substituting only its transport."""
    checkout = root / "checkout"
    checkout.mkdir()
    (root / "bin").mkdir()
    (root / "home").mkdir()
    shim = root / "bin/opencode"
    shim.write_text(
        f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(AGENT)!r}, run_name='__main__')\n"
    )
    shim.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(checkout)], env=env, check=True, timeout=10)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Probe",
            "-c",
            "user.email=probe@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "Controlled baseline",
        ],
        cwd=checkout,
        env=env,
        check=True,
        timeout=10,
    )
    spec = json.loads((BASE / "examples/standalone/investigate-happy.json").read_text())
    answer = json.loads(json.dumps(spec["agents"]["investigate"]).replace("$RUN_ID", root.name))
    save(root / "answer.json", answer)
    for relative, text in spec["artifacts"].items():
        (root / relative).write_text(text)
    save(
        root / "context.json",
        {
            "workflow": "investigate",
            "mode": "live",
            "checkout": str(checkout),
            "inputs": {
                "work": "Probe literal $ARTIFACTS_DIR and $(touch escaped)",
                "target": "Controlled investigate target",
                "scope": "controlled",
                "report": "",
                "related": "[]",
                "publish": "false",
            },
            "config": {
                "agent_argv": [sys.executable, str(AGENT), "--capture"],
                "agent_timeout_seconds": 10,
            },
        },
    )
    run = Run(root)
    run.env = {
        **env,
        "ARTIFACTS_DIR": str(root),
        "WORKFLOW_ID": root.name,
        "INPUTS_WORK": run.ctx["inputs"]["work"],
    }
    result = run.agent(run.nodes["investigate"], "investigate")
    run.check(result, run.nodes["investigate"])
    return run, (root / "prompts/investigate.md").read_text()


def probe(root: pathlib.Path, case: str) -> dict[str, object]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    env = environment(root, case)
    binary = BASE / ".tools/bin/dagu"
    version = subprocess.check_output(
        [str(binary), "version"], env=env, text=True, timeout=10
    ).strip()
    if version != "2.24.0":
        raise RuntimeError(f"Probe requires pinned Dagu 2.24.0, found {version}")
    ports = subprocess.run(
        ["ss", "-ltn"], capture_output=True, text=True, env=env, check=True, timeout=10
    )
    (root / "ports-before.txt").write_text(ports.stdout)
    run, prompt = prepare(root, env)
    options = {
        "provider": "opencode",
        "prompt": prompt,
        "model": "controlled/no-provider",
        "agent": "build",
        "variant": "high",
    }
    if case == "managed":
        options["managed"] = True
    else:
        options["format"] = "json"
    dag = root / "investigate-harness.yaml"
    dag.write_text(
        yaml.safe_dump(
            {
                "type": "graph",
                "working_dir": str(run.repo),
                "max_clean_up_time_sec": 5,
                "env": run.env,
                "steps": [
                    {
                        "id": "investigate",
                        "action": "harness.run",
                        "with": options,
                        "timeout_sec": 2 if case == "timeout" else 20,
                        "stdout": str(root / "harness.stdout"),
                    }
                ],
            },
            sort_keys=False,
        )
    )
    command = [str(binary), "--dagu-home", str(root / "dagu")]
    validation = subprocess.run(
        [*command, "validate", str(dag)], env=env, capture_output=True, text=True, timeout=15
    )
    (root / "validate.log").write_text(validation.stdout + validation.stderr)
    worker = (
        subprocess.Popen(
            [sys.executable, str(AGENT), "--worker"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if case in ("timeout", "signal")
        else None
    )
    proc = None
    try:
        if worker is not None:
            (root / "worker.pid").write_text(str(worker.pid))
        proc = subprocess.Popen(
            [*command, "start", str(dag)],
            env=env,
            cwd=BASE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        if case == "signal":
            deadline = time.monotonic() + 10
            while not (root / "invocation.json").exists():
                if proc.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Controlled client did not start before signal deadline")
                time.sleep(0.02)
            proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=30)
        (root / "start.log").write_text(stdout + stderr)
        busy = False
        if worker is not None:
            heartbeat = (root / "heartbeat").read_text()
            time.sleep(0.1)
            busy = worker.poll() is None and (root / "heartbeat").read_text() != heartbeat
        raw = (root / "harness.stdout").read_text() if (root / "harness.stdout").exists() else ""
        certification_error = ""
        try:
            run.check(json.loads(raw), run.nodes["investigate"])
        except json.JSONDecodeError as error:
            certification_error = error.msg
        invocation = root / "invocation.json"
        sent = json.loads(invocation.read_text()) if invocation.exists() else None
        evidence = {
            "case": case,
            "dagu_version": version,
            "validate_exit": validation.returncode,
            "start_exit": proc.returncode,
            "dagu_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "native_result": next(
                (line[8:] for line in stdout.splitlines() if line.startswith("Result: ")), "unknown"
            ),
            "source_output_certified": not certification_error,
            "certification_error": certification_error,
            "prompt_exact": sent["argv"][1] == prompt if sent else None,
            "api_calls": (root / "api.jsonl").exists(),
            "service_owned_work_still_busy": busy,
            "controlled_client_signalled": (root / "client-signal").exists(),
        }
        if case == "jsonl" and raw:
            decoded = json.loads(final_answer(raw))
            run.check(decoded, run.nodes["investigate"])
            evidence["adapter_output_certified"] = True
        save(root / "evidence.json", evidence)
        return evidence
    finally:
        if proc is not None:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        if worker is not None:
            worker.terminate()
            worker.wait(timeout=5)
        save(
            root / "cleanup.json",
            {
                "dagu_reaped": proc is not None and proc.poll() is not None,
                "worker_reaped": worker is None or worker.poll() is not None,
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES, default="jsonl")
    parser.add_argument("--state-dir", type=pathlib.Path)
    args = parser.parse_args()
    root = args.state_dir or BASE / ".runs/harness-probe" / (args.case + "-" + uuid.uuid4().hex[:8])
    print(json.dumps({**probe(root, args.case), "evidence_dir": str(root)}, indent=2))


if __name__ == "__main__":
    main()
