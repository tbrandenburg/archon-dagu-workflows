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


def stage_fixture(tmp_path, adapter, review_marker):
    root = tmp_path / "artifacts"
    engine.save(
        root / "context.json",
        {
            "mode": "real",
            "repo": str(tmp_path),
            "fixture": {"rounds": [{}]},
            "command_config": {
                "commands": {
                    "code": [sys.executable, str(adapter)],
                    "review": [
                        sys.executable,
                        "-c",
                        f"open({str(review_marker)!r}, 'w').write('called')",
                    ],
                },
                "stage_timeout_seconds": 0.5,
                "test_transport": True,
            },
        },
    )
    engine.save(root / "state.json", {"round": 0, "done": False, "light_review": True})
    engine.save(root / "round-1/implement.json", {"green": True})
    engine.save(root / "round-1/scope.json", {"head_matches": True})
    return root


@pytest.mark.parametrize("mode", ["failure", "timeout"])
def test_unverified_session_cancellation_is_terminal_for_lens_stage(tmp_path, mode):
    adapter = tmp_path / "adapter.py"
    review_marker = tmp_path / "review-called"
    adapter.write_text(
        "import sys,time\n"
        "print('OpenCode adapter: cancellation unverified for session ses_test', file=sys.stderr, flush=True)\n"
        + ("time.sleep(60)\n" if mode == "timeout" else "sys.exit(1)\n")
    )
    root = stage_fixture(tmp_path, adapter, review_marker)
    wrapper = tmp_path / "run_stage.py"
    wrapper.write_text(
        "import pathlib,sys\n"
        f"sys.path.insert(0,{str(pathlib.Path(engine.__file__).parents[1])!r})\n"
        "from archon_dagu import engine\n"
        f"engine.stage(pathlib.Path({str(root)!r}), 'code')\n"
        f"engine.stage(pathlib.Path({str(root)!r}), 'review')\n"
    )
    result = subprocess.run(
        [sys.executable, str(wrapper)], capture_output=True, text=True, timeout=8
    )
    assert result.returncode != 0
    assert not (root / "round-1/code.json").exists()
    assert not review_marker.exists()
    assert b"cancellation unverified" in (root / "requests/1-code.stderr.log").read_bytes()


def test_verified_open_code_lens_failure_remains_incomplete(tmp_path):
    adapter = tmp_path / "adapter.py"
    adapter.write_text(
        "import sys\n"
        "print('OpenCode adapter: session ses_test cancellation verified; model failed', file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    root = stage_fixture(tmp_path, adapter, tmp_path / "review-called")
    engine.stage(root, "code")
    assert engine.load(root / "round-1/code.json")["completed"] is False


@pytest.mark.parametrize("spawn_window", [False, True])
def test_live_stage_captured_unverified_cancellation_is_terminal(
    tmp_path, monkeypatch, spawn_window
):
    fake_cli = tmp_path / "opencode"
    worker_pid = tmp_path / "server-worker.pid"
    session_created = tmp_path / "session-created"
    adapter_pid = tmp_path / "adapter.pid"
    fake_cli.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, signal, subprocess, sys, time\n"
        f"pidfile=pathlib.Path({str(worker_pid)!r})\n"
        f"sessionfile=pathlib.Path({str(session_created)!r})\n"
        "args=sys.argv[1:]\n"
        "if args[0]=='api':\n"
        " rest=args[1:]; data=json.loads(rest[1]) if rest[0]=='--data' else None; path=rest[-1]\n"
        " if path=='/api/session': sessionfile.write_text(data['id']); print(json.dumps({'data':{'id':data['id']}})); sys.exit(0)\n"
        " if path.endswith('/interrupt?resume=false'):\n"
        "  if os.environ.get('FAKE_INTERRUPT_FAIL'): sys.exit(2)\n"
        "  worker=int(pidfile.read_text()); os.kill(worker, signal.SIGTERM); print('{\"interrupted\":true}'); sys.exit(0)\n"
        " if path.endswith('/wait'): sys.exit(0)\n"
        "if args[0]=='run':\n"
        f" pathlib.Path({str(adapter_pid)!r}).write_text(str(os.getpid()))\n"
        " worker=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        " pidfile.write_text(str(worker.pid))\n"
        " signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        " time.sleep(60)\n"
    )
    fake_cli.chmod(0o755)
    review_marker = tmp_path / "review-called"
    root = tmp_path / "production-artifacts"
    repo = pathlib.Path(engine.__file__).parents[2]
    engine.save(
        root / "context.json",
        {
            "mode": "real",
            "repo": str(repo),
            "work": "test work",
            "pull_request": 1,
            "branch": "test-branch",
            "part": "code",
            "errors": [],
            "fixture": {"rounds": [{}]},
            "command_config": {
                "commands": {
                    "code": [sys.executable, "-m", "archon_dagu.live_stage"],
                    "review": [
                        sys.executable,
                        "-c",
                        f"open({str(review_marker)!r}, 'w').write('called')",
                    ],
                },
                "agent_argv": [sys.executable, "-m", "archon_dagu.opencode", "--agent", "build"],
                "stage_timeout_seconds": 1.5,
                "test_transport": True,
            },
        },
    )
    engine.save(root / "state.json", {"round": 0, "done": False, "light_review": True})
    engine.save(root / "round-1/implement.json", {"green": True})
    engine.save(root / "round-1/scope.json", {"head_matches": True})
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    if spawn_window:
        hook = tmp_path / "sitecustomize.py"
        hook.write_text(
            "import os,signal,subprocess\n"
            "original=subprocess.Popen\n"
            "sent=False\n"
            f"pidfile={str(adapter_pid)!r}\n"
            "def spawn(args,*a,**kw):\n"
            " global sent\n"
            " if not sent and isinstance(args,(list,tuple)) and 'archon_dagu.opencode' in args:\n"
            "  sent=True; child=original(args,*a,**kw); open(pidfile,'w').write(str(child.pid)); os.kill(os.getpid(),signal.SIGTERM); return child\n"
            " return original(args,*a,**kw)\n"
            "subprocess.Popen=spawn\n"
        )
        monkeypatch.setenv(
            "PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", "")
        )
    else:
        monkeypatch.setenv("FAKE_INTERRUPT_FAIL", "1")
    wrapper = tmp_path / "production_stage.py"
    wrapper.write_text(
        "import pathlib,sys\n"
        f"sys.path.insert(0,{str(repo / 'src')!r})\n"
        "from archon_dagu import engine\n"
        f"engine.stage(pathlib.Path({str(root)!r}), 'code')\n"
        + ("" if spawn_window else f"engine.stage(pathlib.Path({str(root)!r}), 'review')\n")
    )
    process = subprocess.Popen(
        [sys.executable, str(wrapper)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        _, stderr = process.communicate(timeout=8)
        if spawn_window:
            assert process.returncode == 0, stderr
            assert engine.load(root / "round-1/code.json")["completed"] is False
            assert not session_created.exists()
            assert not worker_pid.exists()
            assert adapter_pid.exists()
            wait_for_process_exit(int(adapter_pid.read_text()), timeout=2)
        else:
            assert process.returncode != 0, stderr
            assert not (root / "round-1/code.json").exists()
            assert not (root / "review/code.md").exists()
            assert not review_marker.exists()
            stage_log = (root / "requests/1-code.stderr.log").read_bytes()
            assert b"cancellation unverified" in stage_log
            assert worker_pid.exists()
            assert process_state(int(worker_pid.read_text())) not in ("", "Z")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)
        if worker_pid.exists():
            try:
                os.kill(int(worker_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if adapter_pid.exists():
            try:
                os.kill(int(adapter_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


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
        "start_new_session=True)\n"
        "    child_pid.write_text(str(proc.pid))\n"
        "    deadline = time.monotonic() + 5\n"
        "    while time.monotonic() < deadline:\n"
        "        if ready.exists() and ready.read_text() == 'ready':\n"
        "            break\n"
        "        time.sleep(0.01)\n"
        "    assert ready.exists() and ready.read_text() == 'ready', 'child did not reach spawn barrier'\n"
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
