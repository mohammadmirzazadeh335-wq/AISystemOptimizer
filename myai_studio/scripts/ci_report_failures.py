"""Turn a pytest JUnit report (and its log) into GitHub check annotations.

Raw runner logs live on a host that is not always reachable (for example from
a sandboxed reviewer), while annotations are readable through the API. So this
script prints one ``::error`` line per failing test and never raises: a broken
or missing report must not hide why the job went red.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _first_line(node: ET.Element | None) -> str:
    if node is None:
        return ""
    text = (node.get("message") or "").strip() or (node.text or "").strip()
    return text.splitlines()[0][:300] if text else ""


def _from_report(path: Path) -> tuple[list[tuple[str, str, str]], int, int]:
    """(file, title, reason) per failure, plus totals for tests and skips."""
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:  # noqa: BLE001 - never hide the reason
        print(f"::warning::could not parse {path}: {type(exc).__name__}: {exc}")
        return [], 0, 0
    found: list[tuple[str, str, str]] = []
    total = skipped = 0
    for case in root.iter("testcase"):
        total += 1
        failure = case.find("failure")
        error = case.find("error")
        if failure is None and error is None:
            if case.find("skipped") is not None:
                skipped += 1
            continue
        node = failure if failure is not None else error
        name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        target = case.get("file") or (case.get("classname") or "").replace(".", "/") + ".py"
        found.append((target, name, _first_line(node) or "failed"))
    return found, total, skipped


def _from_log(path: Path) -> list[tuple[str, str, str]]:
    """Fallback for a run that died before JUnit was written."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found: list[tuple[str, str, str]] = []
    for line in lines:
        if line.startswith("FAILED "):
            body = line[len("FAILED ") :].strip()
            node, _, reason = body.partition(" - ")
            path_hint, _, name = node.partition("::")
            found.append((path_hint, node, reason.strip()[:300] or "failed"))
    return found


def main(argv: list[str]) -> int:
    # A Windows runner's stdout is cp1252 unless told otherwise; printing a
    # test name with "›" or a Persian log line then raises UnicodeEncodeError
    # and the whole report step dies silently. Force UTF-8 and never fail on
    # an unencodable character again.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = argv[1:]
    report = Path(args[0]) if args and not args[0].startswith("-") else Path("pytest.xml")
    log = Path("pytest.log")
    if "--log" in args:
        index = args.index("--log")
        if index + 1 < len(args):
            log = Path(args[index + 1])

    found, total, skipped = _from_report(report) if report.is_file() else ([], 0, 0)
    if not found:
        found = _from_log(log)
    if not report.is_file():
        print(f"::warning::no JUnit report at {report}; falling back to {log}")
    if not found:
        # pytest can exit non-zero without a single failing test: a collection
        # error, an interrupted run, a crash during session teardown. The parsed
        # report then says nothing, so the raw log tail is the only evidence —
        # print it as an annotation, which is readable without the runner logs.
        tail = []
        if log.is_file():
            try:
                lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = [line for line in lines if line.strip()][-8:]
            except OSError:
                tail = []
        if tail:
            joined = " | ".join(line.strip()[:160] for line in tail)
            print(f"::error::pytest exited non-zero with no parsed failure; log tail: {_escape(joined)}")
        else:
            print(f"::error::pytest exited non-zero and left no readable log at {log}")

    for path_hint, name, reason in found[:40]:
        # "::" ends a workflow command, so the title must not contain it.
        title = _escape(name.replace("::", " › "))
        print(f"::error file={path_hint},title={title}::{_escape(reason)}")
    if len(found) > 40:
        print(f"::error::{len(found) - 40} more failing tests were not listed")
    print(f"::notice::pytest: {total} tests, {len(found)} failed, {skipped} skipped")

    if "--write" in args:
        index = args.index("--write")
        if index + 1 < len(args):
            target = Path(args[index + 1])
            try:
                target.write_text(
                    "\n".join(f"{path_hint}::{name} - {reason}" for path_hint, name, reason in found) or "no failures",
                    encoding="utf-8",
                )
            except OSError:
                pass

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and found:
        lines = ["### Failing tests", "", "| Test | Reason |", "| --- | --- |"]
        for _path, name, reason in found[:60]:
            cell = reason.replace("|", "/")[:160]
            lines.append(f"| `{name}` | {cell} |")
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError:
            pass
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
