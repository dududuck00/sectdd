"""Fixed-call feedback interventions, separate from the frozen paper methods."""
from __future__ import annotations

METHODS = {
    "blind": ("none", "none"),
    "binary": ("all", "binary"),
    "fixed_raw": ("fixed", "raw"),
    "priority_raw": ("priority", "raw"),
    "fixed_structured": ("fixed", "structured"),
    "priority_structured": ("priority", "structured"),
}
REVISION = "Review and revise the implementation to satisfy the original requirements. Return one complete fenced Python module."


def select_cases(cases, selection, seen):
    failed = [c for c in cases if not c["passed"]]
    if selection == "fixed":
        return sorted(failed, key=lambda c: c["case_id"])[:2]
    if selection == "priority":
        return sorted(failed, key=lambda c: (c["marker"] != "security", seen.get(c["case_id"], 0), c["case_id"]))[:2]
    return []


def make_feedback(method, visible, seen):
    selection, rendering = METHODS[method]
    if rendering == "none":
        return REVISION, []
    status = "Visible test suite: " + ("PASS." if visible["summary"]["all_passed"] else "FAIL.")
    if rendering == "binary" or visible["summary"]["all_passed"]:
        return REVISION + "\n\n" + status, []
    chosen = select_cases(visible["cases"], selection, seen)
    blocks = []
    for case in chosen:
        failure = "\n".join((case.get("failure") or "Test did not complete successfully.").splitlines()[-12:])
        if rendering == "structured":
            failure = f"Case: {case['case_id']}\nType: {case['marker']}\nExecutable property: {case['description']}\nObserved failure:\n{failure}"
        blocks.append(failure)
        seen[case["case_id"]] = seen.get(case["case_id"], 0) + 1
    return REVISION + "\n\n" + status + "\n\n" + "\n\n".join(blocks), [c["case_id"] for c in chosen]
