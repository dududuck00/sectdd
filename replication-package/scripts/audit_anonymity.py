#!/usr/bin/env python3
"""Fail if the review artifact contains common identity or credential leaks."""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {"", ".bib", ".cfg", ".csv", ".in", ".ini", ".json", ".jsonl", ".lock", ".md", ".py", ".sh", ".tex", ".txt", ".yaml", ".yml"}
PATTERNS = {
    "author username": re.compile("liang" + "yunhao", re.I),
    "development hostname": re.compile("132" + "-A800", re.I),
    "absolute development path": re.compile(r"/(?:home|data)/[^\s\"']*/(?:sectdd|Qwen)", re.I),
    "unredacted API key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
}
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)


def scan_text(label: str, text: str) -> list[str]:
    findings = []
    for kind, pattern in PATTERNS.items():
        match = pattern.search(text)
        if match:
            findings.append(f"{label}: {kind}: {match.group(0)[:100]}")
    # Generated programs and security tests legitimately contain synthetic
    # addresses.  Author-facing prose and manuscript metadata must not.
    if label.endswith((".md", ".tex", ".bib")):
        match = EMAIL.search(text)
        if match:
            findings.append(f"{label}: email address: {match.group(0)[:100]}")
    return findings


def main() -> None:
    findings: list[str] = []
    forbidden_names = {".git", ".env", "id_rsa", "credentials.json"}
    for path in sorted(ROOT.rglob("*")):
        if path.name in forbidden_names:
            findings.append(f"{path.relative_to(ROOT)}: forbidden file or directory")
        if not path.is_file() or path.name == "MANIFEST.sha256":
            continue
        relative = path.relative_to(ROOT).as_posix()
        try:
            if path.name.endswith(".jsonl.gz"):
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    for number, line in enumerate(stream, 1):
                        findings.extend(scan_text(f"{relative}:{number}", line))
            elif path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", "Makefile"}:
                findings.extend(scan_text(relative, path.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError) as error:
            findings.append(f"{relative}: could not audit text: {error}")
    if findings:
        print("Anonymous-artifact audit failed:", file=sys.stderr)
        for finding in findings[:100]:
            print(f"- {finding}", file=sys.stderr)
        raise SystemExit(1)
    print("OK: no configured identity, path, email, or credential leak detected.")


if __name__ == "__main__":
    main()
