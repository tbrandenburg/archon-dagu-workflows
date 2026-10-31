"""Controlled OpenCode-shaped executable for the issue-22 probe; no network calls."""

import json
import os
import pathlib
import signal
import sys
import time


def main() -> None:
    root = pathlib.Path(os.environ["PROBE_ROOT"])
    args = sys.argv[1:]
    if args == ["--capture"]:
        (root / "rendered.md").write_text(sys.stdin.read())
        print((root / "answer.json").read_text())
        return
    if args == ["--worker"]:
        while True:
            (root / "heartbeat").write_text(str(time.monotonic_ns()))
            time.sleep(0.02)
    if args[0] == "api":
        with (root / "api.jsonl").open("a") as handle:
            handle.write(json.dumps(args) + "\n")
        path = args[-1]
        if path == "/api/session/ses_controlled/interrupt?resume=false":
            os.kill(int((root / "worker.pid").read_text()), signal.SIGTERM)
            print('{"interrupted":true}')
            return
        raise SystemExit("Unsupported controlled API call; no OpenCode service is contacted")
    if args[0] != "run":
        raise SystemExit("Only controlled run/api operations are permitted")
    record = {
        "pid": os.getpid(),
        "argv": args,
        "stdin": sys.stdin.read(),
        "cwd": os.getcwd(),
        "env": {
            key: os.environ.get(key) for key in ("ARTIFACTS_DIR", "WORKFLOW_ID", "INPUTS_WORK")
        },
    }
    (root / "invocation.json").write_text(json.dumps(record))

    def stop(signum: int, _frame: object) -> None:
        (root / "client-signal").write_text(str(signum))
        raise SystemExit(128 + signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    events = [
        {"type": "text", "part": {"messageID": "earlier", "text": "Controlled commentary"}},
        {
            "type": "text",
            "part": {"messageID": "final", "text": (root / "answer.json").read_text()},
        },
        {"type": "step_finish", "part": {"messageID": "final", "reason": "stop"}},
    ]
    for event in events:
        event["sessionID"] = "ses_controlled"
        print(json.dumps(event), flush=True)
    if os.environ["PROBE_CASE"] in ("timeout", "signal"):
        time.sleep(60)


if __name__ == "__main__":
    main()
