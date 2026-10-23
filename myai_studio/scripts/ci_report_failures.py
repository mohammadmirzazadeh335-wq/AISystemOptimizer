"""Turn a pytest JUnit report into GitHub check annotations.

The CI runner keeps its raw logs on a host that is not always reachable
(for example from a sandboxed reviewer), but annotations are readable through
the API. One ``::error`` line per failing test therefore makes a red Windows
run diagnosable without the log.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _escape(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _first_line(node: ET.Element | None) -> str:
    if node is None:
        return ""
    text = (node.get("message") or "").strip() or (node.text or "").strip()
    return text.splitlines()[0][:400] if text else ""


def main(argv: list[str]) -> int:
    report = Path(argv[1] if len(argv) > 1 else "pytest.xml")
    if not report.is_file():
        print(f"::warning::no pytest report at {report}")
        return 0
    root = ET.parse(report).getroot()
    failed = skipped = total = 0
    for case in root.iter("testcase"):
        total += 1
        failure = case.find("failure")
        error = case.find("error")
        if failure is None and error is None:
            if case.find("skipped") is not None:
                skipped += 1
            continue
        failed += 1
        name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
        reason = _first_line(failure if failure is not None else error) or "failed"
        file_hint = (case.get("file") or case.get("classname") or "").replace("::", "/")
        # "::" ends a workflow command, so the title must not contain it.
        title = _escape(name.replace("::", " › "))
        print(f"::error file={file_hint},title={title}::{_escape(reason)}")
    print(f"::notice::pytest: {total} tests, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
