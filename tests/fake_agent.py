#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    args = sys.argv[1:]
    exit_code = os.environ.get("FAKE_AGENT_EXIT_CODE")
    if exit_code:
        sys.exit(int(exit_code))
    out_idx = args.index("-o")
    out_path = args[out_idx + 1]
    prompt = args[-1]
    prompt_file = os.environ.get("FAKE_AGENT_PROMPT_FILE")
    if prompt_file:
        Path(prompt_file).write_text(prompt, encoding="utf-8")
    args_file = os.environ.get("FAKE_AGENT_ARGS_FILE")
    if args_file:
        Path(args_file).write_text(json.dumps(args), encoding="utf-8")
    env_file = os.environ.get("FAKE_AGENT_ENV_FILE")
    if env_file:
        proxy_env = {key: value for key, value in os.environ.items() if "PROXY" in key.upper()}
        Path(env_file).write_text(json.dumps(proxy_env), encoding="utf-8")
    print(json.dumps({"type": "thread.started", "payload": {"id": "thread-fake-1"}}), flush=True)
    time.sleep(float(os.environ.get("FAKE_AGENT_SLEEP", "0.3")))
    reply = os.environ.get("FAKE_AGENT_REPLY", "这是假的 Codex 回复")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(reply)


if __name__ == "__main__":
    main()
