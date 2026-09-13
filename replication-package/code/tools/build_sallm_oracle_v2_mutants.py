#!/usr/bin/env python3
"""Materialize the primary targeted mutant set for SALLM oracle v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_sallm_oracle_overlay_v2 import QUALIFIED_TASKS, ROOT


MANIFEST = ROOT / "benchmarks/manifests/sallm-v1.json"
OUTPUT = ROOT / "oracles/sallm_v2/mutants/primary"
METADATA = ROOT / "oracles/sallm_v2/mutants/primary.json"

OPERATORS = {
    "Assertion_Author_A_cwe020_0.py": "replace literal separators and full match with wildcard separators and prefix match",
    "Assertion_Author_A_cwe022_0.py": "remove allowed-directory containment check",
    "Assertion_Author_A_cwe079_0.py": "remove HTML output escaping",
    "Assertion_CodeQL_codeql_cwe117_0.py": "remove CR/LF log neutralization",
    "Matching_Author_A_cwe327_0.py": "replace SHA-256 verification with SHA-1",
    "Matching_StackOverflow_SO_cwe078_0.py": "replace argv execution with shell=True",
    "Tainted_Author_A_cwe089_0.py": "replace parameterized query with SQL concatenation",
    "Tainted_Author_A_cwe611_0.py": "remove explicit external-entity protections",
    "Tainted_CodeQL_codeql_cwe113_0.py": "remove response-header validation",
    "Tainted_CodeQL_codeql_cwe1236_0.py": "remove spreadsheet-formula neutralization",
    "Tainted_StackOverflow_SO_cwe094_0.py": "replace literal parsing with eval",
}


def record(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tasks = {task["task_id"]: task for task in manifest["tasks"]}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    entries = {}
    for task_id in QUALIFIED_TASKS:
        source = ROOT / tasks[task_id]["source"]["reference_file"]["path"]
        destination = OUTPUT / task_id
        destination.write_bytes(source.read_bytes())
        entries[task_id] = {
            "mutation_operator": OPERATORS[task_id],
            "candidate": record(destination),
            "provenance": {
                "type": "benchmark_vulnerable_reference",
                "source": record(source),
            },
        }
    payload = {
        "schema_version": 1,
        "mutation_set_id": "sallm-oracle-v2-primary",
        "description": (
            "One threat-aligned security-fix reversion per qualified task. "
            "Each mutant must retain functionality and fail security."
        ),
        "task_count": len(entries),
        "tasks": entries,
    }
    METADATA.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(entries)} mutants and {METADATA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
