#!/usr/bin/env python3
"""Inner focused-operator mutation runner.

Never invoke this file directly. It refuses to run without a token-matched sentinel in a
disposable copy created by run_disposable.py.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable


ROOT = Path.cwd().resolve()
SCRIPT = Path(__file__).resolve()
CONFIG_PATH = SCRIPT.with_name("config.json")


@dataclass(frozen=True)
class Candidate:
    mutantId: str
    file: str
    sourceSha256: str
    offset: int
    line: int
    column: int
    operator: str
    original: str
    replacement: str
    sourceLine: str


@dataclass
class CommandResult:
    command: list[str]
    returnCode: int
    timedOut: bool
    durationSeconds: float
    stdoutTail: str
    stderrTail: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def tail(value: str, limit: int = 4000) -> str:
    return value[-limit:]


def run(command: list[str], timeout: int) -> CommandResult:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env={**os.environ, "CI": "true", "NO_COLOR": "1"},
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
    return CommandResult(
        command=command,
        returnCode=process.returncode if process.returncode is not None else 124,
        timedOut=timed_out,
        durationSeconds=round(time.monotonic() - started, 3),
        stdoutTail=tail(stdout),
        stderrTail=tail(stderr),
    )


def require_disposable_copy() -> dict[str, Any]:
    token = os.environ.get("BRERC_MUTATION_DISPOSABLE_TOKEN", "")
    sentinel = ROOT / ".brerc-mutation-disposable"
    context_path_raw = os.environ.get("BRERC_MUTATION_CONTEXT", "")
    if not token or not sentinel.is_file() or sentinel.read_text(encoding="utf-8") != token:
        raise RuntimeError("missing or invalid disposable-run sentinel")
    if not context_path_raw:
        raise RuntimeError("missing disposable-run context")
    context_path = Path(context_path_raw).resolve()
    if context_path.parent != ROOT or not context_path.is_file():
        raise RuntimeError("disposable-run context is outside the temporary copy")
    context: object = json.loads(context_path.read_text(encoding="utf-8"))
    if not isinstance(context, dict) or context.get("schemaVersion") != 1:
        raise RuntimeError("invalid disposable-run context")
    original = context.get("originalWebRoot")
    if not isinstance(original, str) or ROOT == Path(original).resolve():
        raise RuntimeError("inner runner would modify the original working tree")
    return context


def load_config() -> dict[str, Any]:
    raw: object = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schemaVersion") != 1:
        raise RuntimeError("invalid mutation config")
    return raw


def code_mask(source: str) -> list[bool]:
    """Conservative TypeScript lexer: strings/comments/templates are not mutation sites."""
    mask = [True] * len(source)
    i = 0
    state = "code"
    quote = ""
    while i < len(source):
        char = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if state == "code":
            if char == "/" and nxt == "/":
                mask[i] = mask[i + 1] = False
                state = "line-comment"
                i += 2
                continue
            if char == "/" and nxt == "*":
                mask[i] = mask[i + 1] = False
                state = "block-comment"
                i += 2
                continue
            if char in ("'", '"', "`"):
                mask[i] = False
                quote = char
                state = "string"
                i += 1
                continue
        elif state == "line-comment":
            mask[i] = False
            if char == "\n":
                state = "code"
        elif state == "block-comment":
            mask[i] = False
            if char == "*" and nxt == "/":
                mask[i + 1] = False
                state = "code"
                i += 2
                continue
        else:
            mask[i] = False
            if char == "\\":
                if i + 1 < len(source):
                    mask[i + 1] = False
                i += 2
                continue
            if char == quote:
                state = "code"
        i += 1
    return mask


def candidates(config: dict[str, Any]) -> tuple[list[Candidate], dict[str, str]]:
    found: list[Candidate] = []
    source_hashes: dict[str, str] = {}
    for relative in config["sources"]:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"invalid mutation source: {relative}")
        source = path.read_text(encoding="utf-8")
        source_hash = sha256_bytes(source.encode("utf-8"))
        source_hashes[relative] = source_hash
        mask = code_mask(source)
        lines = source.splitlines()
        for operator in config["operators"]:
            pattern = re.compile(operator["pattern"])
            for match in pattern.finditer(source):
                if not all(mask[index] for index in range(match.start(), match.end())):
                    continue
                original = match.group(0)
                replacement = operator["replacement"]
                if original == replacement:
                    continue
                line = source.count("\n", 0, match.start()) + 1
                prior_newline = source.rfind("\n", 0, match.start())
                column = match.start() - prior_newline
                identity = "\0".join(
                    [
                        relative,
                        source_hash,
                        str(match.start()),
                        operator["id"],
                        original,
                        replacement,
                    ]
                )
                found.append(
                    Candidate(
                        mutantId=sha256_bytes(identity.encode("utf-8")),
                        file=relative,
                        sourceSha256=source_hash,
                        offset=match.start(),
                        line=line,
                        column=column,
                        operator=operator["id"],
                        original=original,
                        replacement=replacement,
                        sourceLine=lines[line - 1].strip()[:200],
                    )
                )
    found.sort(key=lambda item: (item.file, item.offset, item.operator))
    return found, source_hashes


def command_version(command: list[str]) -> str:
    result = run(command, 30)
    value = (result.stdoutTail or result.stderrTail).strip().splitlines()
    return value[-1] if result.returnCode == 0 and value else "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-mutants", type=int, default=None)
    parser.add_argument("--verify-kills", action="store_true")
    return parser.parse_args()


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    score = summary["focusedOperatorScore"]
    score_text = "not reported (incomplete run)" if score is None else f"{score:.1f}%"
    lines = [
        "# Focused accessibility mutation report",
        "",
        f"- Status: **{report['status']}**",
        f"- Run ID: `{report['runId']}`",
        f"- Started: `{report['startedAt']}`",
        f"- Finished: `{report['finishedAt']}`",
        f"- Focused operator score: **{score_text}**",
        f"- Candidates: **{summary['candidates']}**; processed: **{summary['processed']}**",
        f"- Killed: **{summary['killed']}**; survived: **{summary['survived']}**",
        f"- Invalid TypeScript: **{summary['invalid']}**; timed out: **{summary['timedOut']}**; "
        f"inconclusive: **{summary['inconclusive']}**",
        "",
        "This is a focused regex-operator sweep, not a general TypeScript mutation score. "
        "Invalid, timed-out and inconclusive mutants are excluded from the denominator. "
        "No survivor is automatically described as equivalent.",
        "",
        "## Surviving mutants",
        "",
        "| ID | File | Line:column | Operator | Source |",
        "|---|---|---:|---|---|",
    ]
    for item in report["results"]["survived"]:
        safe_source_line = item["sourceLine"].replace("|", "\\|")[:100]
        lines.append(
            f"| `{item['mutantId'][:12]}` | `{item['file']}` | "
            f"{item['line']}:{item['column']} | `{item['operator']}` | "
            f"`{safe_source_line}` |"
        )
    if not report["results"]["survived"]:
        lines.append("| — | — | — | — | No survivors in this run |")
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            f"- Commit: `{report['provenance']['git']['commit']}`",
            f"- Branch: `{report['provenance']['git']['branch']}`",
            f"- Original tree clean: `{report['provenance']['git']['treeClean']}`",
            f"- Input-manifest digest: `{report['provenance']['inputManifestSha256']}`",
            f"- Baseline tests observed: `{report['provenance']['baselineTestsObserved']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    context = require_disposable_copy()
    config = load_config()
    all_candidates, source_hashes = candidates(config)
    selected = all_candidates
    limited = args.max_mutants is not None
    if limited:
        if args.max_mutants <= 0:
            raise RuntimeError("--max-mutants must be positive")
        selected = all_candidates[: args.max_mutants]

    started = utc_now()
    run_id = secrets.token_hex(16)
    typecheck_command = list(config["commands"]["typecheck"])
    tests_command = list(config["commands"]["tests"])
    baseline_timeout = int(config["timeoutsSeconds"]["baseline"])
    typecheck_timeout = int(config["timeoutsSeconds"]["typecheckPerMutant"])
    test_timeout = int(config["timeoutsSeconds"]["testsPerMutant"])

    baseline_typecheck = run(typecheck_command, baseline_timeout)
    baseline_tests = run(tests_command, baseline_timeout)
    if (
        baseline_typecheck.returnCode != 0
        or baseline_typecheck.timedOut
        or baseline_tests.returnCode != 0
        or baseline_tests.timedOut
    ):
        raise RuntimeError("disposable baseline is not green; refusing to mutate")

    test_count_match = re.search(
        r"Tests\s+(\d+)\s+passed",
        f"{baseline_tests.stdoutTail}\n{baseline_tests.stderrTail}",
    )
    tests_observed = int(test_count_match.group(1)) if test_count_match else None

    buckets: dict[str, list[dict[str, Any]]] = {
        "killed": [],
        "survived": [],
        "invalid": [],
        "timedOut": [],
        "inconclusive": [],
    }
    originals = {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in config["sources"]
    }

    for number, candidate in enumerate(selected, start=1):
        print(
            f"[{number}/{len(selected)}] {candidate.file}:{candidate.line}:"
            f"{candidate.column} {candidate.operator}",
            flush=True,
        )
        path = ROOT / candidate.file
        original_source = originals[candidate.file]
        if sha256_bytes(original_source.encode("utf-8")) != candidate.sourceSha256:
            raise RuntimeError(f"source hash changed before mutant {candidate.mutantId}")
        mutated = (
            original_source[: candidate.offset]
            + candidate.replacement
            + original_source[candidate.offset + len(candidate.original) :]
        )
        record = asdict(candidate)
        restored = False
        try:
            path.write_text(mutated, encoding="utf-8")
            typecheck = run(typecheck_command, typecheck_timeout)
            record["typecheck"] = asdict(typecheck)
            if typecheck.timedOut:
                buckets["timedOut"].append({**record, "phase": "typecheck"})
                continue
            if typecheck.returnCode != 0:
                buckets["invalid"].append(record)
                continue
            tests = run(tests_command, test_timeout)
            record["tests"] = asdict(tests)
            if tests.timedOut:
                buckets["timedOut"].append({**record, "phase": "tests"})
            elif tests.returnCode == 0:
                buckets["survived"].append(record)
            elif not args.verify_kills:
                buckets["killed"].append(record)
            else:
                path.write_text(original_source, encoding="utf-8")
                restored = True
                control = run(tests_command, test_timeout)
                record["unmutatedControl"] = asdict(control)
                if control.returnCode == 0 and not control.timedOut:
                    buckets["killed"].append(record)
                else:
                    buckets["inconclusive"].append(
                        {**record, "reason": "unmutated control suite was not green"}
                    )
        finally:
            if not restored or path.read_text(encoding="utf-8") != original_source:
                path.write_text(original_source, encoding="utf-8")

    final_typecheck = run(typecheck_command, baseline_timeout)
    final_tests = run(tests_command, baseline_timeout)
    originals_intact = all(
        (ROOT / relative).read_text(encoding="utf-8") == value
        for relative, value in originals.items()
    )
    post_green = (
        originals_intact
        and final_typecheck.returnCode == 0
        and not final_typecheck.timedOut
        and final_tests.returnCode == 0
        and not final_tests.timedOut
    )
    complete = (
        not limited
        and post_green
        and not buckets["timedOut"]
        and not buckets["inconclusive"]
    )
    denominator = len(buckets["killed"]) + len(buckets["survived"])
    score = (
        round(100 * len(buckets["killed"]) / denominator, 1)
        if complete and denominator > 0
        else None
    )

    input_manifest = context.get("inputManifest", {})
    input_manifest_digest = sha256_bytes(
        json.dumps(input_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "complete" if complete else "incomplete",
        "runId": run_id,
        "startedAt": started,
        "finishedAt": utc_now(),
        "summary": {
            "candidates": len(all_candidates),
            "processed": len(selected),
            "killed": len(buckets["killed"]),
            "survived": len(buckets["survived"]),
            "invalid": len(buckets["invalid"]),
            "timedOut": len(buckets["timedOut"]),
            "inconclusive": len(buckets["inconclusive"]),
            "focusedOperatorScore": score,
            "scoreFormula": "killed / (killed + survived); only for complete runs",
        },
        "scope": {
            "description": "Focused regex operator sweep, not general TypeScript mutation testing",
            "sources": config["sources"],
            "operators": [item["id"] for item in config["operators"]],
            "verifyKills": args.verify_kills,
            "limitedToFirstN": args.max_mutants,
        },
        "results": buckets,
        "baseline": {
            "typecheck": asdict(baseline_typecheck),
            "tests": asdict(baseline_tests),
        },
        "postRun": {
            "typecheck": asdict(final_typecheck),
            "tests": asdict(final_tests),
            "sourcesRestored": originals_intact,
        },
        "provenance": {
            "git": context.get("git", {}),
            "inputManifest": input_manifest,
            "inputManifestSha256": f"sha256:{input_manifest_digest}",
            "sourceSha256": {
                key: f"sha256:{value}" for key, value in source_hashes.items()
            },
            "baselineTestsObserved": tests_observed,
            "tools": {
                "python": platform.python_version(),
                "node": command_version(["node", "--version"]),
                "npm": command_version(["npm", "--version"]),
                "typescript": command_version(["./node_modules/.bin/tsc", "--version"]),
                "vitest": command_version(["./node_modules/.bin/vitest", "--version"]),
            },
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "timeoutsSeconds": config["timeoutsSeconds"],
        },
    }
    output = args.output_dir.resolve()
    atomic_write(output / "mutation-report.json", json.dumps(report, indent=2) + "\n")
    atomic_write(output / "mutation-report.md", render_markdown(report))
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary": report["summary"],
                "reports": str(output),
            },
            indent=2,
        )
    )
    return 0 if post_green else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"inner mutation runner refused to continue: {error}", file=sys.stderr)
        raise SystemExit(2)
