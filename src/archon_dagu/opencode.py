"""Translate OpenCode's JSONL event stream to the original Archon stage output."""

import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time

API_TIMEOUT = 1.2
SESSION_CREATE_TIMEOUT = 12.0
CLEANUP_TIMEOUT = 2.8
TERM_TIMEOUT = 0.15
SESSION_ID = re.compile(r"^ses[a-zA-Z0-9_-]+$")


class Cancelled(Exception):
    """The adapter received a cancellation signal."""


def final_answer(stream):
    """Keep final-message text, excluding prior commentary, tools and reasoning."""
    messages = {}
    finishes = {}
    last = None
    for line in stream.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            raise ValueError("OpenCode emitted invalid JSON events") from None
        if not isinstance(event, dict):
            raise ValueError("OpenCode event must be an object")
        if event.get("type") == "error":
            raise ValueError("OpenCode reported an error; inspect its diagnostics/session")
        part = event.get("part", {})
        if not isinstance(part, dict):
            raise ValueError("OpenCode event part must be an object")
        if event.get("type") == "step_finish":
            finishes[part.get("messageID")] = part.get("reason")
        if event.get("type") != "text":
            continue
        message = part.get("messageID")
        text = part.get("text")
        if not isinstance(message, str) or not message or not isinstance(text, str):
            raise ValueError("OpenCode text event requires messageID and text")
        messages.setdefault(message, []).append(text)
        last = message
    if last is None or not (answer := "".join(messages[last])).strip():
        raise ValueError("OpenCode returned no final assistant text")
    if last in finishes and finishes[last] not in ("stop", "end_turn"):
        raise ValueError("OpenCode final message did not finish normally")
    return answer


def _stop(proc):
    """Terminate and reap exactly the process group started for this client."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=TERM_TIMEOUT)
        return
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()


def _command(args, cwd):
    command = ["opencode", "run", "--session", args.session, "--format", "json"]
    for name in ("model", "agent", "variant"):
        if value := getattr(args, name):
            command.extend(["--" + name, value])
    return command


def _api(method, path, data, cwd, env, deadline, cancelled):
    command = ["opencode"]
    if data is not None:
        command.extend(["api", "--data", json.dumps(data, separators=(",", ":")), method, path])
    else:
        command.extend(["api", method, path])
    proc = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    try:
        while True:
            if cancelled():
                raise Cancelled
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("OpenCode API operation timed out")
            try:
                stdout, _ = proc.communicate(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if proc.returncode:
            raise RuntimeError("OpenCode API request failed")
        return stdout
    finally:
        _stop(proc)


def _cancel_session(session, cwd, env, deadline, cancelled):
    verified = False
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        response = _api(
            "post",
            f"/api/session/{session}/interrupt?resume=false",
            None,
            cwd,
            env,
            min(deadline, time.monotonic() + min(API_TIMEOUT, remaining)),
            lambda: False,
        )
        payload = json.loads(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("interrupted"), bool):
            raise ValueError("invalid interrupt response")
        verified = True
    except (OSError, RuntimeError, TimeoutError, ValueError, json.JSONDecodeError):
        verified = False
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        _api(
            "post",
            f"/api/experimental/session/{session}/wait",
            None,
            cwd,
            env,
            min(deadline, time.monotonic() + min(API_TIMEOUT, remaining)),
            lambda: False,
        )
        return verified
    except (OSError, RuntimeError, TimeoutError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="OpenCode provider/model; default: OpenCode configuration")
    parser.add_argument("--agent", help="OpenCode agent; default: OpenCode configuration")
    parser.add_argument("--variant", help="Provider-specific reasoning variant")
    args = parser.parse_args()
    session = "ses_" + secrets.token_hex(16)
    if not SESSION_ID.fullmatch(session):
        print("OpenCode adapter: generated invalid session ID", file=sys.stderr)
        return 1
    cwd = os.getcwd()
    env = {**os.environ, "PWD": cwd}
    prompt = sys.stdin.read()
    cancelled_signal = []
    previous = {}

    def on_signal(signum, _frame):
        if not cancelled_signal:
            cancelled_signal.append(signum)
            if run_proc is not None:
                try:
                    os.killpg(run_proc.pid, signum)
                except ProcessLookupError:
                    pass
                raise Cancelled

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, on_signal)

    run_proc = None
    try:
        response = _api(
            "post",
            "/api/session",
            {"id": session, "location": {"directory": cwd}},
            cwd,
            env,
            time.monotonic() + SESSION_CREATE_TIMEOUT,
            lambda: bool(cancelled_signal),
        )
        data = json.loads(response)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("data"), dict)
            or data["data"].get("id") != session
        ):
            raise ValueError("OpenCode returned an unexpected session")
        if cancelled_signal:
            raise Cancelled

        command = _command(argparse.Namespace(**vars(args), session=session), cwd)
        run_proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        if cancelled_signal:
            raise Cancelled
        stdout, _ = run_proc.communicate(prompt)
        if cancelled_signal:
            raise Cancelled
        if run_proc.returncode:
            raise ValueError(f"OpenCode exited with status {run_proc.returncode}")
        answer = final_answer(stdout)
        blocked = signal.pthread_sigmask(signal.SIG_BLOCK, set(previous))
        try:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            if cancelled_signal:
                raise Cancelled
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
        sys.stdout.write(answer)
        sys.stdout.flush()
        return 0
    except Cancelled:
        if run_proc is not None:
            _stop(run_proc)
        verified = _cancel_session(
            session, cwd, env, time.monotonic() + CLEANUP_TIMEOUT, lambda: False
        )
        message = (
            f"OpenCode adapter: cancellation unverified for session {session}"
            if not verified
            else f"OpenCode adapter: session {session} cancellation verified"
        )
        print(message, file=sys.stderr)
        return 1
    except (OSError, RuntimeError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        if run_proc is not None:
            _stop(run_proc)
        verified = _cancel_session(
            session, cwd, env, time.monotonic() + CLEANUP_TIMEOUT, lambda: False
        )
        message = (
            f"OpenCode adapter: cancellation unverified for session {session}; {exc}"
            if not verified
            else f"OpenCode adapter: session {session} cancellation verified; {exc}"
        )
        print(message, file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    sys.exit(main())
