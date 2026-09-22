"""Launch the presentation tier, bound to loopback only.

    python scripts/run_ui.py

The address and port are not defaults to be overridden casually: the TDD binds
the app to 127.0.0.1:8501 and the network perimeter section relies on it. The
app serves a customer-facing analysis from a database with no authentication in
front of it, so binding to 0.0.0.0 would publish it to the local network.
``--host`` exists for the case where someone genuinely needs that, and it says
so loudly rather than doing it quietly.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP = PROJECT_ROOT / "src" / "app" / "streamlit_app.py"

LOOPBACK = "127.0.0.1"
PORT = 8501


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default=LOOPBACK,
                        help="Anything other than 127.0.0.1 exposes the app "
                             "beyond this machine; you will be warned.")
    args = parser.parse_args()

    if args.host != LOOPBACK:
        print(f"\n  WARNING: binding to {args.host}, not {LOOPBACK}.")
        print("  This app has no authentication and serves analysis read from")
        print("  a local database. On a non-loopback address anyone who can")
        print("  reach this machine can read it.\n")

    command = [sys.executable, "-m", "streamlit", "run", str(APP),
               "--server.address", args.host,
               "--server.port", str(args.port),
               "--server.headless", "true",
               "--browser.gatherUsageStats", "false"]
    print(f"  http://{args.host}:{args.port}\n")
    return subprocess.call(command, cwd=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
