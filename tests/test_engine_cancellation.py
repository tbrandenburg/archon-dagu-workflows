import os
import pathlib
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


def test_sigterm_during_spawn_stops_new_process_group(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    ready = tmp_path / "child-ready"
    child_pid = tmp_path / "child.pid"
    child_code = (
        "import pathlib,sys,time; "
        "sys.stderr.write('spawn-window evidence\\n'); sys.stderr.flush(); "
        "pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(60)"
    )
    engine.save(
        artifacts / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "command_config": {
                "commands": {"ci": [sys.executable, "unused"]},
                "stage_timeout_seconds": 30,
            },
        },
    )
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import os, pathlib, signal, subprocess, sys, time\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from archon_dagu import engine\n"
        "real_popen = subprocess.Popen\n"
        "ready = pathlib.Path(sys.argv[3])\n"
        "child_pid = pathlib.Path(sys.argv[4])\n"
        "child_code = sys.argv[5]\n"
        "def interrupting_popen(*args, **kwargs):\n"
        "    proc = real_popen([sys.executable, '-c', child_code, str(ready)], "
        "stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, "
        "text=True, start_new_session=True)\n"
        "    child_pid.write_text(str(proc.pid))\n"
        "    deadline = time.monotonic() + 5\n"
        "    while time.monotonic() < deadline and not ready.exists():\n"
        "        time.sleep(0.01)\n"
        "    assert ready.exists(), 'child did not reach spawn barrier'\n"
        "    os.kill(os.getpid(), signal.SIGTERM)\n"
        "    return proc\n"
        "subprocess.Popen = interrupting_popen\n"
        "engine.invoke(pathlib.Path(sys.argv[2]), 'ci', {}, 1, {})\n"
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            str(wrapper),
            str(pathlib.Path(engine.__file__).parents[1]),
            str(artifacts),
            str(ready),
            str(child_pid),
            child_code,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _, stderr = proc.communicate(timeout=8)
        assert proc.returncode != 0
        assert ready.read_text() == "ready"
        assert "spawn-window evidence" in (artifacts / "requests/1-ci.stderr.log").read_text()
        wait_for_process_exit(int(child_pid.read_text()), timeout=2)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
        if child_pid.exists():
            try:
                os.kill(int(child_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("parent_signal", [signal.SIGTERM, signal.SIGINT])
def test_parent_signal_stops_adapter_process_group(tmp_path, parent_signal):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    pid_file = tmp_path / "descendant.pid"
    adapter_pid_file = tmp_path / "adapter.pid"
    adapter = tmp_path / "adapter.py"
    child_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    adapter.write_text(
        "import os,pathlib,subprocess,sys,time; "
        f"pathlib.Path({str(adapter_pid_file)!r}).write_text(str(os.getpid())); "
        f"child=subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); "
        "sys.stderr.write('adapter evidence\\n'); sys.stderr.flush(); time.sleep(60)"
    )
    engine.save(
        artifacts / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "command_config": {
                "commands": {"ci": [sys.executable, str(adapter)]},
                "stage_timeout_seconds": 30,
            },
        },
    )
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import pathlib,sys; sys.path.insert(0, sys.argv[1]); "
        "from archon_dagu import engine; "
        "engine.invoke(pathlib.Path(sys.argv[2]), 'ci', {}, 1, {})"
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            str(wrapper),
            str(pathlib.Path(engine.__file__).parents[1]),
            str(artifacts),
        ],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_file.exists():
            if proc.poll() is not None:
                break
            time.sleep(0.02)
        assert pid_file.exists(), "adapter did not launch its descendant"
        descendant_pid = int(pid_file.read_text())
        adapter_pid = int(adapter_pid_file.read_text())
        os.killpg(proc.pid, parent_signal)
        time.sleep(0.05)
        os.killpg(proc.pid, signal.SIGINT if parent_signal == signal.SIGTERM else signal.SIGTERM)
        proc.communicate(timeout=7)
        assert proc.returncode != 0
        assert "adapter evidence" in (artifacts / "requests/1-ci.stderr.log").read_text()
        wait_for_process_exit(descendant_pid, timeout=2)
        wait_for_process_exit(adapter_pid, timeout=2)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if adapter_pid_file.exists():
            adapter_pid = int(adapter_pid_file.read_text())
            try:
                os.kill(adapter_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.killpg(adapter_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.communicate()
