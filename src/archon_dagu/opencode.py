"""Translate OpenCode's JSONL event stream to the original Archon stage output."""

import argparse
import json
import subprocess
import sys


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
    # Some CLI versions omit the final step_finish; never invent a success marker.
    if last in finishes and finishes[last] not in ("stop", "end_turn"):
        raise ValueError("OpenCode final message did not finish normally")
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="OpenCode provider/model; default: OpenCode configuration")
    parser.add_argument("--agent", help="OpenCode agent; default: OpenCode configuration")
    parser.add_argument("--variant", help="Provider-specific reasoning variant")
    args = parser.parse_args()
    command = ["opencode", "run", "--format", "json"]
    for name in ("model", "agent", "variant"):
        if value := getattr(args, name):
            command.extend(["--" + name, value])
    # stdin avoids command-line size limits and exposes no prompt in process argv.
    # Inherit the caller's cwd, environment and process group for cancellation.
    try:
        result = subprocess.run(command, input=sys.stdin.read(), text=True, stdout=subprocess.PIPE)
        if result.returncode:
            raise ValueError(f"OpenCode exited with status {result.returncode}")
        answer = final_answer(result.stdout)
    except (OSError, ValueError) as exc:
        print(f"OpenCode adapter: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
