"""P0 matrix entry point. Full file delivery and sample gates belong to R2/R5.

Only the public HTTP API is reachable here. No Runner module is imported.
An empty P0 fixture cannot certify any platform; this command exits blocked.
"""

import argparse
import json
from pathlib import Path
from urllib.request import urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--platforms", help="Comma-separated platform keys")
    mode.add_argument("--all", action="store_true")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8111")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).parent / "fixtures" / "coldstart_cases.json",
    )
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if not isinstance(cases, list):
        parser.error("cases must be a JSON array")
    with urlopen(
        f"{args.api_base_url.rstrip('/')}/health/ready", timeout=5
    ) as response:
        ready = response.status == 200
    print(
        json.dumps(
            {
                "result": "blocked",
                "reason": "p0_matrix_not_implemented",
                "api_ready": ready,
                "sample_count": len(cases),
            }
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
