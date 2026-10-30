"""Real-process regressions for cancellation and failures while stopping adapters."""

import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

from archon_dagu import engine


def wait_for(path):
    deadline = time.monotonic() + 8
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), f"Process did not reach barrier: {path}"


def assert_stopped(pid):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = subprocess.run(
            ["ps", "-p", str(pid), "-o", "state="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
        if not state or state.startswith("Z"):
            return
        time.sleep(0.02)
    pytest.fail(f"Owned process {pid} survived cleanup")


@pytest.fixture
def adapter(tmp_path):
    def configure(source, stage="ci", timeout=1):
        script = tmp_path / "adapter.py"
        script.write_text(
            "import os,pathlib,signal,subprocess,sys,time\n"
            f"pathlib.Path({str(tmp_path / 'adapter.pid')!r}).write_text(str(os.getpid()))\n"
            + source
        )
        root = tmp_path / "artifacts"
        engine.save(
            root / "context.json",
            {
                "mode": "real",
                "repo": str(tmp_path),
                "fixture": {"rounds": [{}]},
                "command_config": {
                    "commands": {stage: [sys.executable, str(script)]},
                    "stage_timeout_seconds": timeout,
                    "test_transport": True,
                },
            },
        )
        return root

    yield configure
    for path in tmp_path.glob("*.pid"):
        pid = int(path.read_text())
        for target in (pid, -pid):
            try:
                os.kill(target, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("parent_signal", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("phase", ["cleanup_wait", "handler_restoration"])
def test_cancellation_during_timeout_cleanup_never_continues(
    adapter, tmp_path, parent_signal, phase
):
    stopping = tmp_path / "stopping"
    continued = tmp_path / "continued"
    root = adapter(
        f"signal.signal(signal.SIGTERM, lambda *_: pathlib.Path({str(stopping)!r}).touch())\n"
        "sys.stderr.write('cleanup evidence\\n'); sys.stderr.flush()\n"
        "time.sleep(60)\n",
        stage="code",
    )
    engine.save(root / "state.json", {"round": 0, "done": False, "light_review": True})
    engine.save(root / "round-1/implement.json", {"green": True})
    engine.save(root / "round-1/scope.json", {"head_matches": True})
    wrapper = tmp_path / "wrapper.py"
    hook = (
        "mask = signal.pthread_sigmask\n"
        "def cancel_before_mask(how, signals):\n"
        f"    if how == signal.SIG_BLOCK: os.kill(os.getpid(), {int(parent_signal)})\n"
        "    return mask(how, signals)\n"
        "signal.pthread_sigmask = cancel_before_mask\n"
        if phase == "handler_restoration"
        else ""
    )
    wrapper.write_text(
        "import os,pathlib,signal,sys\n"
        f"sys.path.insert(0,{str(pathlib.Path(engine.__file__).parents[1])!r})\n"
        "from archon_dagu import engine\n"
        + hook
        + f"engine.stage(pathlib.Path({str(root)!r}),'code')\n"
        f"pathlib.Path({str(continued)!r}).touch()\n"
    )
    proc = subprocess.Popen(
        [sys.executable, str(wrapper)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        wait_for(stopping)
        if phase == "cleanup_wait":
            proc.send_signal(parent_signal)
        proc.communicate(timeout=10)
        assert proc.returncode != 0
        assert not continued.exists()
        assert not (root / "round-1/code.json").exists()
        assert b"cleanup evidence" in (root / "requests/1-code.stderr.log").read_bytes()
        assert_stopped(int((tmp_path / "adapter.pid").read_text()))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)


@pytest.mark.parametrize("stream", [1, 2])
def test_malformed_output_cannot_interrupt_group_cleanup(adapter, tmp_path, stream):
    child_pid = tmp_path / "child.pid"
    child = (
        "import os,pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); os.close(1); os.close(2); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
    )
    root = adapter(
        f"subprocess.Popen([sys.executable,'-c',{child!r},{str(child_pid)!r}])\n"
        f"while not pathlib.Path({str(child_pid)!r}).exists(): time.sleep(.01)\n"
        f"os.write({stream},b'bad bytes: \\xff\\n')\n"
        "time.sleep(60)\n"
    )
    with pytest.raises(TimeoutError, match="ci command exceeded"):
        engine.invoke(root, "ci", {}, 1, {})
    assert_stopped(int(child_pid.read_text()))
    assert_stopped(int((tmp_path / "adapter.pid").read_text()))
    evidence = (root / "requests/1-ci.stderr.log").read_bytes()
    assert evidence == (b"bad bytes: \xff\n" if stream == 2 else b"")


def test_communication_error_still_reaps_spawned_adapter(adapter, monkeypatch, tmp_path):
    ready = tmp_path / "ready"
    root = adapter(f"pathlib.Path({str(ready)!r}).touch()\ntime.sleep(60)\n")
    original = subprocess.Popen
    spawned = []

    def start(*args, **kwargs):
        proc = original(*args, **kwargs)
        spawned.append(proc)
        wait_for(ready)
        communicate = proc.communicate

        def fail_once(*args, **kwargs):
            proc.communicate = communicate
            raise OverflowError("injected communication failure")

        proc.communicate = fail_once
        return proc

    monkeypatch.setattr(subprocess, "Popen", start)
    try:
        with pytest.raises(OverflowError, match="injected communication failure"):
            engine.invoke(root, "ci", {}, 1, {})
        assert spawned[0].poll() is not None
        assert (root / "requests/1-ci.stderr.log").is_file()
    finally:
        for proc in spawned:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)


def test_maximum_stage_deadline_runs_a_short_adapter(adapter):
    root = adapter('print(\'{"state":"green"}\')\n', timeout=86400)
    result = engine.invoke(root, "ci", {}, 1, {})
    assert result == {"state": "green"}
    assert (root / "requests/1-ci.stderr.log").read_bytes() == b""
