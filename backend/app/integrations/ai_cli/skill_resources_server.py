from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.integrations.ai_cli.skill_resources import TOOL, SkillResources


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    resources = SkillResources(parser.parse_args().workspace)
    for line in sys.stdin:
        if len(line.encode()) > 16 * 1024:
            raise ValueError("skill resource protocol limit")
        message = json.loads(line)
        identifier = message.get("id")
        if identifier is None:
            continue
        method = message.get("method")
        result: object = {}
        if method == "initialize":
            result = {
                "protocolVersion": message.get("params", {}).get(
                    "protocolVersion", "2025-06-18"
                ),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "skill-resources", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": [TOOL]}
        elif method == "tools/call":
            params = message.get("params", {})
            result = resources.call(params.get("name", ""), params.get("arguments", {}))
        print(
            json.dumps({"jsonrpc": "2.0", "id": identifier, "result": result}),
            flush=True,
        )


if __name__ == "__main__":
    main()
