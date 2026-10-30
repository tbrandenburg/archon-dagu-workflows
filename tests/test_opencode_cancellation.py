"""Cancellation tests use only a fake OpenCode CLI and fake session service."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from archon_dagu import engine

FAKE_CLI = r"""#!/usr/bin/env python3
import json, os, pathlib, signal, subprocess, sys, time
args = sys.argv[1:]
state = pathlib.Path(os.environ["FAKE_STATE"])
if args[0] == "api":
    rest = args[1:]
    data = json.loads(rest[1]) if rest[0] == "--data" else None
    path = rest[-1]
    if path == "/api/session":
        (state / "created.json").write_text(json.dumps(data))
        worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (state / "owned.pid").write_text(str(worker.pid))
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (state / "unrelated.pid").write_text(str(unrelated.pid))
        if os.environ.get("CREATE_SLOW"):
            time.sleep(float(os.environ["CREATE_SLOW"]))
        if os.environ.get("CREATE_LOST"):
            sys.exit(0)
        print(json.dumps({"data": {"id": data["id"]}}))
    elif path.endswith("/interrupt?resume=false"):
        sid = path.split("/")[-2]
        (state / "interrupted").write_text(sid)
        target = int((state / "owned.pid").read_text())
        os.kill(target, signal.SIGTERM)
        if os.environ.get("INTERRUPT_FAIL"):
            sys.exit(2)
        print('{"interrupted":true}')
    elif path.endswith("/wait"):
        (state / "waited").write_text(path.split("/")[-2])
        if os.environ.get("WAIT_HANG"):
            time.sleep(60)
    sys.exit(0)
if args[0] == "run":
    session = args[args.index("--session") + 1]
    (state / "run.json").write_text(json.dumps({"args": args, "prompt": sys.stdin.read(), "cwd": os.getcwd(), "pwd": os.environ.get("PWD")}))
    if os.environ.get("RUN_SLEEP"):
        time.sleep(float(os.environ["RUN_SLEEP"]))
    if os.environ.get("SIGNAL_BOUNDARY"):
        os.kill(os.getppid(), int(os.environ["SIGNAL_BOUNDARY"]))
    print(json.dumps({"type":"text","part":{"messageID":"answer","text":"{\"ready\":true}"}}), flush=True)
    time.sleep(60) if os.environ.get("RUN_HANG") else None
"""


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def wait_stopped(pid, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = subprocess.run(
                ["ps", "-p", str(pid), "-o", "state="], capture_output=True, text=True, timeout=1
            ).stdout.strip()
        except subprocess.TimeoutExpired:
            state = ""
        if not state or state.startswith("Z"):
            return
        time.sleep(0.02)
    pytest.fail(f"owned process {pid} remained active")


@pytest.fixture
def fake(tmp_path):
    fake_cli = tmp_path / "opencode"
    fake_cli.write_text(FAKE_CLI)
    fake_cli.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "FAKE_STATE": str(state),
    }
    yield state, env
    for name in ("owned.pid", "unrelated.pid"):
        path = state / name
        if path.exists():
            try:
                os.kill(int(path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def launch(fake, cwd, env=None, timeout=5):
    state, base_env = fake
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "archon_dagu.opencode",
            "--model",
            "provider/model",
            "--agent",
            "build",
        ],
        input="prompt contents",
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**base_env, **(env or {})},
        timeout=timeout,
    )


@pytest.mark.parametrize("cancel_signal", [signal.SIGTERM, signal.SIGINT])
def test_signal_interrupts_only_owned_session_and_verifies_idle(fake, tmp_path, cancel_signal):
    state, _ = fake
    run = launch(fake, tmp_path, {"SIGNAL_BOUNDARY": str(int(cancel_signal))})
    assert run.returncode != 0 and run.stdout == ""
    assert "cancellation verified" in run.stderr
    owned = int((state / "owned.pid").read_text())
    unrelated = int((state / "unrelated.pid").read_text())
    wait_stopped(owned)
    assert pid_alive(unrelated)
    session = json.loads((state / "created.json").read_text())["id"]
    assert (state / "interrupted").read_text() == session
    assert (state / "waited").read_text() == session


def test_create_response_loss_cancels_known_id_and_never_runs(fake, tmp_path):
    state, _ = fake
    run = launch(fake, tmp_path, {"CREATE_LOST": "1"})
    assert run.returncode != 0 and run.stdout == ""
    assert "cancellation verified" in run.stderr
    assert not (state / "run.json").exists()
    assert (state / "interrupted").read_text() == json.loads((state / "created.json").read_text())[
        "id"
    ]


def test_create_can_take_longer_than_cleanup_budget(fake, tmp_path):
    run = launch(fake, tmp_path, {"CREATE_SLOW": "1.35"})
    assert run.returncode == 0
    assert json.loads(run.stdout) == {"ready": True}


@pytest.mark.parametrize("cancel_signal", [signal.SIGTERM, signal.SIGINT])
def test_signal_at_final_unmask_cannot_emit_success(fake, tmp_path, cancel_signal):
    hook = tmp_path / "sitecustomize.py"
    hook.write_text(
        "import os, signal\n"
        "original = signal.pthread_sigmask\n"
        "sent = False\n"
        "def mask(how, signals):\n"
        " global sent\n"
        " if how == signal.SIG_SETMASK and not sent:\n"
        "  sent = True; os.kill(os.getpid(), int(os.environ['BOUNDARY_SIGNAL']))\n"
        " return original(how, signals)\n"
        "signal.pthread_sigmask = mask\n"
    )
    _, env = fake
    run = launch(
        fake,
        tmp_path,
        {
            "PYTHONPATH": str(tmp_path) + os.pathsep + env.get("PYTHONPATH", ""),
            "BOUNDARY_SIGNAL": str(int(cancel_signal)),
        },
    )
    assert run.returncode != 0 and run.stdout == ""


@pytest.mark.parametrize("failure", [{"INTERRUPT_FAIL": "1"}, {"WAIT_HANG": "1"}])
def test_unverified_cancellation_never_emits_answer(fake, tmp_path, failure):
    run = launch(fake, tmp_path, {"SIGNAL_BOUNDARY": str(int(signal.SIGTERM)), **failure})
    assert run.returncode != 0 and run.stdout == ""
    assert "cancellation unverified" in run.stderr


def test_engine_timeout_cancels_server_owned_worker(fake, tmp_path, monkeypatch):
    state, env = fake
    artifacts = tmp_path / "artifacts"
    engine.save(
        artifacts / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "command_config": {
                "commands": {
                    "ci": [
                        sys.executable,
                        "-c",
                        "import json,subprocess,sys; r=json.load(sys.stdin); subprocess.run(r['context']['command_config']['agent_argv'], input='prompt', text=True, check=True)",
                    ],
                },
                "agent_argv": [sys.executable, "-m", "archon_dagu.opencode", "--agent", "build"],
                "stage_timeout_seconds": 2,
            },
        },
    )
    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setenv("FAKE_STATE", str(state))
    monkeypatch.setenv("RUN_SLEEP", "60")
    with pytest.raises(TimeoutError, match="ci command exceeded"):
        engine.invoke(artifacts, "ci", {}, 1, {})
    assert (state / "interrupted").exists()
    wait_stopped(int((state / "owned.pid").read_text()))
    assert pid_alive(int((state / "unrelated.pid").read_text()))
