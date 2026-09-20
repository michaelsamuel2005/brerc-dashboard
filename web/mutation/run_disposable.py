#!/usr/bin/env python3
"""Run the focused accessibility mutation sweep in a disposable copy.

This is the only supported entry point. It never asks the inner runner to modify the
working tree: the exact current snapshot (including uncommitted source/tests) is copied
to a system temporary directory, dependencies are installed there, reports are copied
back atomically, and the original mutation inputs are re-hashed afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
WEB_ROOT = SCRIPT.parents[1]
CONFIG_PATH = SCRIPT.with_name("config.json")
DEFAULT_OUTPUT = WEB_ROOT / "test-results" / "a11y-mutation"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config() -> dict[str, Any]:
    raw: object = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schemaVersion") != 1:
        raise ValueError("mutation/config.json has an unsupported schema")
    sources = raw.get("sources")
    if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
        raise ValueError("mutation/config.json sources must be strings")
    return raw


def guarded_paths(config: dict[str, Any]) -> list[Path]:
    relative = [
        "package.json",
        "package-lock.json",
        "tsconfig.a11y.json",
        "mutation/config.json",
        "mutation/run_disposable.py",
        "mutation/mutate_inner.py",
        *config["sources"],
    ]
    paths: list[Path] = []
    for item in relative:
        path = WEB_ROOT / item
        if not path.is_file():
            raise FileNotFoundError(f"required mutation input is missing: {item}")
        if path.is_symlink():
            raise RuntimeError(f"refusing a symlinked mutation input: {item}")
        paths.append(path)
    return paths


def manifest(paths: Iterable[Path]) -> dict[str, str]:
    return {
        str(path.relative_to(WEB_ROOT)): f"sha256:{sha256_file(path)}"
        for path in sorted(paths)
    }


def git_value(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=WEB_ROOT,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def git_context() -> dict[str, object]:
    status = git_value(["status", "--porcelain"])
    clean = None if status == "unknown" else status == ""
    return {
        "branch": git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": git_value(["rev-parse", "HEAD"]),
        "treeClean": clean,
    }


def ignore_copy(directory: str, names: list[str]) -> set[str]:
    ignored = {
        ".git",
        "node_modules",
        "dist",
        "coverage",
        "test-results",
        "playwright-report",
        "screenshots",
        ".vite-cache",
    }
    ignored.update(name for name in names if name.startswith(".env"))
    return ignored.intersection(names)


def run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> tuple[int, str, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        return process.returncode or 124, stdout, stderr, True


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(6)}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="report destination (default: test-results/a11y-mutation)",
    )
    parser.add_argument(
        "--max-mutants",
        type=int,
        default=None,
        help="run only the first N candidates as a harness smoke test; no score is produced",
    )
    parser.add_argument(
        "--verify-kills",
        action="store_true",
        help="rerun the unmutated control suite after every apparent kill",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_mutants is not None and args.max_mutants <= 0:
        raise ValueError("--max-mutants must be positive")

    config = load_config()
    inputs = guarded_paths(config)
    before = manifest(inputs)
    output = args.output_dir if args.output_dir.is_absolute() else WEB_ROOT / args.output_dir
    install_timeout = int(config["timeoutsSeconds"]["install"])

    with tempfile.TemporaryDirectory(prefix="brerc-a11y-mutation-") as tmp:
        temporary_web = Path(tmp) / "web"
        shutil.copytree(WEB_ROOT, temporary_web, ignore=ignore_copy, symlinks=False)

        after_copy = manifest(inputs)
        if before != after_copy:
            raise RuntimeError("mutation inputs changed while the disposable snapshot was copied")
        for relative, expected in before.items():
            copied = temporary_web / relative
            if not copied.is_file() or copied.is_symlink():
                raise RuntimeError(f"invalid copied mutation input: {relative}")
            if f"sha256:{sha256_file(copied)}" != expected:
                raise RuntimeError(f"copied mutation input changed: {relative}")

        token = secrets.token_urlsafe(32)
        sentinel = temporary_web / ".brerc-mutation-disposable"
        sentinel.write_text(token, encoding="utf-8")
        context_path = temporary_web / ".brerc-mutation-context.json"
        context_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "originalWebRoot": str(WEB_ROOT),
                    "inputManifest": before,
                    "git": git_context(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment.update(
            {
                "BRERC_MUTATION_DISPOSABLE_TOKEN": token,
                "BRERC_MUTATION_CONTEXT": str(context_path),
                "CI": "true",
                "NO_COLOR": "1",
            }
        )

        print(f"Preparing disposable mutation copy: {temporary_web}")
        install = [
            "npm",
            "ci",
            "--ignore-scripts",
            "--no-audit",
            "--fund=false",
        ]
        code, stdout, stderr, timed_out = run_process(
            install,
            cwd=temporary_web,
            env=environment,
            timeout=install_timeout,
        )
        if code != 0 or timed_out:
            sys.stderr.write(stdout)
            sys.stderr.write(stderr)
            raise RuntimeError("dependency installation failed in the disposable copy")

        temporary_output = temporary_web / "mutation" / "reports"
        command = [
            sys.executable,
            "mutation/mutate_inner.py",
            "--output-dir",
            str(temporary_output),
        ]
        if args.max_mutants is not None:
            command.extend(["--max-mutants", str(args.max_mutants)])
        if args.verify_kills:
            command.append("--verify-kills")

        code, stdout, stderr, timed_out = run_process(
            command,
            cwd=temporary_web,
            env=environment,
            timeout=max(install_timeout, 24 * 60 * 60),
        )
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        for name in ("mutation-report.json", "mutation-report.md"):
            report = temporary_output / name
            if report.is_file():
                atomic_copy(report, output / name)

        after = manifest(inputs)
        if before != after:
            raise RuntimeError(
                "original mutation inputs changed during the disposable run; reports are untrusted"
            )
        if timed_out:
            raise RuntimeError("the disposable mutation sweep exceeded its outer timeout")
        if code != 0:
            return code

    print(f"Reports copied atomically to {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"mutation runner refused to continue: {error}", file=sys.stderr)
        raise SystemExit(2)
