#!/usr/bin/env python3
"""O'Reilly CLI web UI entry point."""

import argparse
import sys


def _missing_dependency_message(package: str) -> str:
    return (
        f"Missing required dependency `{package}` for O'Reilly HTTP access.\n"
        "Activate the project environment and install requirements:\n"
        "  source .venv/bin/activate\n"
        "  python -m pip install -r requirements.txt\n"
        "If activation did not take, run `.venv/bin/python -m pip install -r requirements.txt` directly.\n"
        "Then rerun the command with the same `python`.\n"
        f"Current Python: {sys.executable}"
    )


def main():
    parser = argparse.ArgumentParser(description="O'Reilly CLI web UI")
    parser.add_argument("-H", "--host", default="localhost", help="Server host")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Server port")
    args = parser.parse_args()

    try:
        from web.server import run_server
    except ModuleNotFoundError as exc:
        if exc.name == "curl_cffi":
            print(_missing_dependency_message("curl_cffi"), file=sys.stderr)
            return 1
        raise

    print("=" * 50)
    print("  O'Reilly CLI")
    print("=" * 50)
    print(f"\n  Open http://{args.host}:{args.port} in your browser\n")
    print("  Press Ctrl+C to stop\n")
    print("=" * 50)

    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
