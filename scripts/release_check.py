#!/usr/bin/env python3
"""Run release readiness checks for oreilly-cli."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    checks = [
        ("version", lambda: check_version(args.expected_version)),
        ("changelog", check_changelog),
        ("git status", lambda: check_git_status(args.allow_dirty)),
        ("cli version", check_cli_version),
        ("unit tests", check_unit_tests),
        ("compile", check_compile),
        ("cli smoke", check_cli_smoke),
        ("mcp import", check_mcp_import),
    ]
    if args.live:
        checks.append(("live smoke", lambda: check_live_smoke(args)))

    for name, check in checks:
        print(f"==> {name}")
        check()
    print("Release checks passed.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local and optional live release checks.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow uncommitted changes during pre-commit release prep.")
    parser.add_argument("--expected-version", help="Require VERSION to match this value.")
    parser.add_argument("--live", action="store_true", help="Run live O'Reilly smoke checks.")
    parser.add_argument("--cookies-file", default=os.environ.get("OREILLY_COOKIES_FILE", "~/.oreilly-cli/cookies.json"))
    parser.add_argument("--live-book-id", default=os.environ.get("OREILLY_RELEASE_BOOK_ID", "9781098120672"))
    parser.add_argument("--keep-smoke-output", action="store_true", help="Keep live export temp output for inspection.")
    return parser


def check_version(expected: str | None = None) -> None:
    version = read_version()
    if not VERSION_RE.fullmatch(version):
        raise SystemExit(f"VERSION is not a semantic version: {version}")
    if expected and version != expected:
        raise SystemExit(f"VERSION {version} does not match expected {expected}")


def check_changelog() -> None:
    version = read_version()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in changelog:
        raise SystemExit(f"CHANGELOG.md is missing a section for {version}")


def check_git_status(allow_dirty: bool) -> None:
    result = run(["git", "status", "--porcelain"], capture=True)
    if result.stdout.strip() and not allow_dirty:
        raise SystemExit("Working tree is dirty. Commit changes or rerun with --allow-dirty.")


def check_cli_version() -> None:
    result = run([sys.executable, "oreilly_cli.py", "--version"], capture=True)
    if read_version() not in result.stdout:
        raise SystemExit(f"CLI version output did not include {read_version()}: {result.stdout.strip()}")


def check_unit_tests() -> None:
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])


def check_compile() -> None:
    run([
        sys.executable,
        "-m",
        "compileall",
        "oreilly_cli.py",
        "mcp_server.py",
        "config.py",
        "cli",
        "core",
        "plugins",
        "tests",
        "scripts",
    ])


def check_cli_smoke() -> None:
    run([sys.executable, "oreilly_cli.py", "--help"], capture=True)
    formats = run([sys.executable, "oreilly_cli.py", "formats", "--json"], capture=True)
    payload = json.loads(formats.stdout)
    for required in ("epub", "markdown", "chunks"):
        if required not in payload.get("formats", []):
            raise SystemExit(f"formats output is missing {required}")
    run([sys.executable, "oreilly_cli.py", "repair-links", "--help"], capture=True)


def check_mcp_import() -> None:
    run([sys.executable, "-c", "import mcp_server; assert mcp_server.oreilly_status"])


def check_live_smoke(args: argparse.Namespace) -> None:
    cookies_file = str(Path(args.cookies_file).expanduser())
    base = [sys.executable, "oreilly_cli.py", "-c", cookies_file]

    status = json.loads(run([*base, "status", "--json"], capture=True).stdout)
    if not status.get("valid"):
        raise SystemExit(f"Live auth is not valid: {status.get('reason')}")

    run([*base, "formats", "--json"], capture=True)
    run([*base, "resolve", args.live_book_id, "--json"], capture=True)
    run([*base, "book", args.live_book_id, "--json"], capture=True)

    temp_root = Path(tempfile.mkdtemp(prefix="oreilly-cli-release-smoke."))
    try:
        export = json.loads(
            run(
                [
                    *base,
                    "export",
                    args.live_book_id,
                    "--format",
                    "chunks",
                    "--skip-images",
                    "--output-dir",
                    str(temp_root),
                    "--json",
                ],
                capture=True,
            ).stdout
        )
        if export.get("errors"):
            raise SystemExit(f"Live export returned errors: {export['errors']}")

        audit = json.loads(run([sys.executable, "oreilly_cli.py", "repair-links", str(temp_root), "--json"], capture=True).stdout)
        if audit.get("files_changed") or audit.get("links_repaired") or audit.get("unresolved"):
            raise SystemExit(f"Live repair audit was not clean: {audit}")
    finally:
        if args.keep_smoke_output:
            print(f"Kept smoke output: {temp_root}")
        else:
            shutil.rmtree(temp_root, ignore_errors=True)


def read_version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def run(command: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
        raise SystemExit(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
