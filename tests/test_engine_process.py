import os
import signal
import subprocess
import sys
import time

import pytest

from archon_dagu import engine


def process_state(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "state="],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def wait_for_process_exit(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = process_state(pid)
        if not state or state.startswith("Z"):
            return
        time.sleep(0.02)
    pytest.fail(f"process {pid} remained active: {process_state(pid)!r}")


def wait_for_spawned_child(monkeypatch, ready):
    original_popen = subprocess.Popen

    def wait_until_ready(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.01)
        assert ready.exists(), "adapter descendant did not reach the ready barrier"
        return proc

    monkeypatch.setattr(subprocess, "Popen", wait_until_ready)


def test_live_adapter_timeout_stops_its_process_group(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    stopped = tmp_path / "child-stopped"
    ready = tmp_path / "child-ready"
    child_pid = tmp_path / "child.pid"
    adapter_pid = tmp_path / "adapter.pid"
    child = (
        "import pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, lambda *_: (pathlib.Path(sys.argv[1]).write_text('stopped'), sys.exit(0))); "
        "pathlib.Path(sys.argv[2]).write_text('ready'); "
        "time.sleep(60)"
    )
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "import os,pathlib,subprocess,sys,time; "
        f"pathlib.Path({str(adapter_pid)!r}).write_text(str(os.getpid())); "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}, {str(stopped)!r}, {str(ready)!r}]); "
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid)); "
        f"deadline=time.monotonic()+5; "
        f"exec(\"while not __import__('pathlib').Path({str(ready)!r}).exists() and time.monotonic()<deadline: time.sleep(0.01)\"); "
        "sys.stderr.write('timeout evidence\\n'); sys.stderr.flush(); "
        "time.sleep(60)"
    )
    engine.save(
        artifacts / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "command_config": {
                "commands": {"ci": [sys.executable, str(adapter)]},
                "stage_timeout_seconds": 0.25,
            },
        },
    )
    wait_for_spawned_child(monkeypatch, ready)

    try:
        with pytest.raises(TimeoutError, match="ci command exceeded 0.25s"):
            engine.invoke(artifacts, "ci", {}, 1, {})

        assert ready.read_text() == "ready"
        assert stopped.read_text() == "stopped"
        assert (artifacts / "requests/1-ci.json").is_file()
        assert "timeout evidence" in (artifacts / "requests/1-ci.stderr.log").read_text()
        wait_for_process_exit(int(child_pid.read_text()), timeout=2)
        wait_for_process_exit(int(adapter_pid.read_text()), timeout=2)
    finally:
        for pid_file in (adapter_pid, child_pid):
            if pid_file.exists():
                pid = int(pid_file.read_text())
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_timeout_kills_term_ignoring_descendant_that_closed_pipes(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    child_pid = tmp_path / "child.pid"
    ready = tmp_path / "child-ready"
    adapter_pid = tmp_path / "adapter.pid"
    child = (
        "import os,pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "os.close(1); os.close(2); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "pathlib.Path(sys.argv[2]).write_text('ready'); time.sleep(60)"
    )
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "import os,pathlib,subprocess,sys,time; "
        f"pathlib.Path({str(adapter_pid)!r}).write_text(str(os.getpid())); "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}, {str(child_pid)!r}, {str(ready)!r}]); "
        "time.sleep(60)"
    )
    engine.save(
        artifacts / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "command_config": {
                "commands": {"ci": [sys.executable, str(adapter)]},
                "stage_timeout_seconds": 0.25,
            },
        },
    )
    wait_for_spawned_child(monkeypatch, ready)

    try:
        with pytest.raises(TimeoutError, match="ci command exceeded 0.25s"):
            engine.invoke(artifacts, "ci", {}, 1, {})

        assert ready.read_text() == "ready"
        wait_for_process_exit(int(child_pid.read_text()), timeout=2)
        wait_for_process_exit(int(adapter_pid.read_text()), timeout=2)
    finally:
        for pid_file in (adapter_pid, child_pid):
            if pid_file.exists():
                pid = int(pid_file.read_text())
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0, -1, 10**400])
def test_invalid_live_timeout_does_not_spawn_adapter(tmp_path, monkeypatch, timeout):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    engine.save(
        artifacts / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "command_config": {
                "commands": {"ci": [sys.executable, "unused"]},
                "stage_timeout_seconds": timeout,
            },
        },
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *args, **kwargs: pytest.fail("adapter was spawned")
    )

    with pytest.raises(ValueError, match="positive number"):
        engine.invoke(artifacts, "ci", {}, 1, {})
