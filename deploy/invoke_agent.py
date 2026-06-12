"""Invoke a deployed ProMate AgentCore runtime (smoke test after deploy).

Usage:
    set AGENT_RUNTIME_ARN=arn:aws:bedrock-agentcore:...
    uv run python deploy/invoke_agent.py "Will PS11752778 fit WDT780SAEM1?"
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import boto3


def main() -> None:
    agent_arn = os.environ.get("AGENT_RUNTIME_ARN", "").strip()
    if not agent_arn:
        print(
            "Set AGENT_RUNTIME_ARN to the runtime ARN from `agentcore deploy` output.",
            file=sys.stderr,
        )
        sys.exit(1)

    prompt = " ".join(sys.argv[1:]).strip() or "Hello from ProMate"
    region = os.environ.get("AWS_REGION", "us-east-1")
    session_id = os.environ.get("RUNTIME_SESSION_ID") or str(uuid.uuid4())

    client = boto3.client("bedrock-agentcore", region_name=region)
    payload = json.dumps({"prompt": prompt}).encode()

    print(f"Invoking {agent_arn} (session={session_id})...")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        runtimeSessionId=session_id,
        payload=payload,
        qualifier="DEFAULT",
    )

    chunks: list[str] = []
    for chunk in response.get("response", []):
        text = chunk.decode("utf-8")
        chunks.append(text)
        print(text, end="", flush=True)
    print()

    # AgentCore streams SSE lines: data: {...}\n\n
    combined = "".join(chunks)
    for line in combined.splitlines():
        if line.startswith("data: "):
            try:
                event = json.loads(line.removeprefix("data: ").strip())
                if event.get("type") == "done":
                    break
            except json.JSONDecodeError:
                continue


if __name__ == "__main__":
    main()
