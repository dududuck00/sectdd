#!/usr/bin/env python3
"""Build the deterministic SALLM pilot oracle overlay v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/benchmarks/sallm_audit_overlay_v1.json"
OUTPUT = ROOT / "configs/benchmarks/sallm_oracle_overlay_v2.json"
TEST_ROOT = ROOT / "oracles/sallm_v2/tests"

QUALIFIED_TASKS = (
    "Assertion_Author_A_cwe020_0.py",
    "Assertion_Author_A_cwe022_0.py",
    "Assertion_Author_A_cwe079_0.py",
    "Assertion_CodeQL_codeql_cwe117_0.py",
    "Matching_Author_A_cwe327_0.py",
    "Matching_StackOverflow_SO_cwe078_0.py",
    "Tainted_Author_A_cwe089_0.py",
    "Tainted_Author_A_cwe611_0.py",
    "Tainted_CodeQL_codeql_cwe113_0.py",
    "Tainted_CodeQL_codeql_cwe1236_0.py",
    "Tainted_StackOverflow_SO_cwe094_0.py",
)
EXCLUDED_PILOT_TASK = "Matching_Author_A_cwe377_0.py"


def file_record(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def main() -> None:
    overlay = json.loads(SOURCE.read_text(encoding="utf-8"))
    overlay["$schema"] = "schemas/sallm_audit_overlay.schema.json"
    overlay["overlay_id"] = "sallm-oracle-overlay-v2"
    overlay["parent_overlay"] = file_record(SOURCE)
    overlay["scope"] = {
        "name": "qwen36-secure-reference-pilot-v1",
        "requested_task_count": 12,
        "qualified_task_ids": list(QUALIFIED_TASKS),
        "excluded_task_ids": [EXCLUDED_PILOT_TASK],
    }
    overlay["test_overrides"] = {
        task_id: file_record(TEST_ROOT / f"test_{task_id}")
        for task_id in QUALIFIED_TASKS
    }
    overlay["exclusions"][EXCLUDED_PILOT_TASK] = {
        "reason_code": "unsatisfiable_security_oracle",
        "details": (
            "The original security method asserts that the same returned "
            "temporary path both is a file and does not exist. No "
            "implementation can satisfy both assertions."
        ),
    }
    overlay["qualification_policy"] = {
        "require_unsafe_functional_pass": True,
        "require_unsafe_security_fail": True,
        "require_safe_functional_pass": True,
        "require_safe_security_pass": True,
        "require_targeted_mutant_functional_pass": True,
        "require_targeted_mutant_security_fail": True,
        "repeat_count": 3,
        "http_5xx_is_security_failure": True,
        "fresh_sandbox_per_test_method": True,
    }
    OUTPUT.write_text(
        json.dumps(overlay, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
