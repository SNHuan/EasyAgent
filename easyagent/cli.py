from __future__ import annotations

import argparse
from pathlib import Path

from easyagent.dashboard.server import DEFAULT_DB_PATH, run_dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="easyagent", description="EasyAgent developer tools.")
    subparsers = parser.add_subparsers(dest="command")

    dashboard_parser = subparsers.add_parser("dashboard", help="Start the local trace dashboard.")
    dashboard_parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite trace database. Defaults to .easyagent/traces.db.",
    )
    dashboard_parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Defaults to 127.0.0.1.")
    dashboard_parser.add_argument("--port", type=int, default=8765, help="Port to bind. Defaults to 8765.")
    dashboard_parser.add_argument("--open", action="store_true", help="Open the dashboard in a browser.")

    args = parser.parse_args(argv)

    if args.command == "dashboard":
        run_dashboard(
            db_path=Path(args.db),
            host=args.host,
            port=args.port,
            open_browser=args.open,
        )
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

