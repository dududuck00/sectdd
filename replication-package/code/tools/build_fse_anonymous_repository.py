#!/usr/bin/env python3
"""Build the double-anonymous FSE review repository from frozen local evidence."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "FSE/anonymous-repository"

MODELS = (
    "qwen25-coder-7b",
    "qwen25-coder-14b",
    "qwen36-27b",
    "deepseek-v4-flash",
)

PRIMARY_RUNS = tuple(
    (benchmark, model, ROOT / "artifacts/paper-expansion-full-v1" / benchmark / model)
    for benchmark in ("cweval", "sallm", "codeguardplus")
    for model in MODELS
)

LEGACY_RUNS = (
    ("cweval", "qwen25-coder-7b", ROOT / "artifacts/main_internal/qwen25-coder-7b-main-002"),
    ("cweval", "qwen25-coder-14b", ROOT / "artifacts/main_internal/qwen25-coder-14b-main-003-corrected"),
    ("cweval", "qwen3-32b", ROOT / "artifacts/main_internal/qwen3-32b-main-002"),
    ("sallm", "qwen25-coder-7b", ROOT / "artifacts/sallm_formal_main/qwen25-coder-7b-main-002"),
    ("sallm", "qwen25-coder-14b", ROOT / "artifacts/sallm_formal_main/qwen25-coder-14b-main-002"),
    ("sallm", "qwen36-27b", ROOT / "artifacts/sallm_formal_main/qwen36-27b-main-002"),
    ("sallm", "deepseek-v4-flash", ROOT / "artifacts/deepseek-external-confirmatory-v1/sallm"),
    ("codeguardplus", "qwen25-coder-14b", ROOT / "artifacts/codeguardplus-breadth-confirmatory-v1/qwen25-coder-14b"),
    ("codeguardplus", "deepseek-v4-flash", ROOT / "artifacts/codeguardplus-breadth-confirmatory-v1/deepseek-v4-flash"),
)

EXPECTED = {"primary": 3200, "legacy": 2705}

TEXT_SUFFIXES = {
    "",
    ".bib",
    ".cfg",
    ".csv",
    ".in",
    ".ini",
    ".json",
    ".jsonl",
    ".lock",
    ".md",
    ".py",
    ".sh",
    ".tex",
    ".txt",
    ".yaml",
    ".yml",
}

COPY_FILES = (
    "protocol.md",
    "oracle_protocol.md",
    "实验记录.md",
    "artifacts/reports/paper-expansion-full-v1.json",
    "artifacts/reports/unified-paper-evidence-v3.json",
    "artifacts/reports/unified-paper-evidence-v4.json",
    "docs/paper-expansion-full-v1-protocol.md",
    "docs/unified-paper-evidence-v4.md",
    "docs/external-benchmark-manifests.md",
    "benchmarks/manifests/paper-expansion-full-v1-input-freeze.json",
    "benchmarks/manifests/paper-expansion-full-v1-results-freeze.json",
    "benchmarks/manifests/paper-expansion-full-v1-runtime-input-correction.json",
    "benchmarks/manifests/paper-evidence-v3-results-freeze.json",
    "benchmarks/manifests/paper-evidence-v4-results-freeze.json",
    "benchmarks/manifests/codeguardplus-paper-expansion-functional-marker-correction-v1.json",
    "benchmarks/manifests/codeguardplus-paper-expansion-v1-semantic-machine-freeze.json",
    "benchmarks/manifests/cweval-paper-expansion-v1-semantic-machine-freeze.json",
    "benchmarks/manifests/sallm-paper-expansion-v1-semantic-machine-freeze.json",
    "configs/experiments/cweval_paper_expansion_full_v1.json",
    "configs/experiments/sallm_paper_expansion_full_v1.json",
    "configs/experiments/codeguardplus_paper_expansion_full_v1.json",
    "configs/oracles/cweval_py_paper_expansion_v1_semantic_machine_visible.json",
    "configs/oracles/cweval_py_paper_expansion_v1_semantic_machine_hidden.json",
    "configs/oracles/sallm_paper_expansion_v1_semantic_machine_visible.json",
    "configs/oracles/sallm_paper_expansion_v1_semantic_machine_hidden.json",
    "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_visible.json",
    "configs/oracles/codeguardplus_paper_expansion_v1_semantic_machine_hidden.json",
    "FSE/paper/main.tex",
    "FSE/paper/references.bib",
    "FSE/paper/main.pdf",
)

COPY_TREES = (
    ("sectdd", "code/sectdd", {".py"}),
    ("tools", "code/tools", {".py"}),
    ("scripts", "code/scripts", {".sh"}),
    ("schemas", "code/schemas", {".json"}),
    ("requirements", "code/requirements", {".txt"}),
    ("oracles/cweval_py/paper_expansion_v1", "oracles/cweval", None),
    ("oracles/sallm_paper_expansion_v1", "oracles/sallm", None),
    ("oracles/sallm_paper_expansion_supplement_v1", "oracles/sallm-supplement", None),
    ("oracles/codeguardplus_paper_expansion_v1", "oracles/codeguardplus", None),
    ("FSE/paper/generated", "paper/generated", {".tex"}),
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sanitize_text(text: str) -> str:
    roots = {
        str(ROOT),
        str(ROOT.resolve()),
        "<ARTIFACT_ROOT>",
        "<ARTIFACT_ROOT>",
    }
    for value in sorted(roots, key=len, reverse=True):
        text = text.replace(value, "<ARTIFACT_ROOT>")
    replacements = (
        ("<MODEL_ROOT>/", "<MODEL_ROOT>/"),
        ("<MODEL_ROOT>/", "<MODEL_ROOT>/"),
        ("<MODEL_ROOT>/", "<MODEL_ROOT>/"),
        ("<ANON_HOME>/", "<ANON_HOME>/"),
        ("anonymous-user", "anonymous-user"),
        ("anonymous-host", "anonymous-host"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "<REDACTED_API_KEY>", text)
    return text


def write_sanitized(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in TEXT_SUFFIXES or source.name in {"LICENSE", "Makefile"}:
        try:
            value = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(source, destination)
        else:
            destination.write_text(sanitize_text(value), encoding="utf-8")
    else:
        shutil.copyfile(source, destination)


def copy_tree(source_name: str, destination_name: str, suffixes: set[str] | None) -> int:
    source = ROOT / source_name
    count = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if suffixes is not None and path.suffix not in suffixes:
            continue
        relative = path.relative_to(source)
        write_sanitized(path, OUT / destination_name / relative)
        count += 1
    return count


def trajectory_paths(run: Path) -> list[Path]:
    return sorted(run.glob("trajectories/*/*/seed_*/trajectory.json"))


def sanitize_json(value: Any) -> Any:
    return json.loads(sanitize_text(json.dumps(value, ensure_ascii=False)))


def export_records(
    name: str, runs: Iterable[tuple[str, str, Path]], evidence_phase: str
) -> dict[str, Any]:
    destination = OUT / "data" / f"{name}-trajectories.jsonl.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    identities: set[tuple[str, str, str, int, str]] = set()
    tasks: set[tuple[str, str]] = set()
    source_hash = hashlib.sha256()
    with destination.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as stream:
                for benchmark, model, run in runs:
                    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
                    paths = trajectory_paths(run)
                    if len(paths) != manifest["trajectory_count"]:
                        raise RuntimeError(f"Incomplete frozen run: {run}")
                    for path in paths:
                        raw_bytes = path.read_bytes()
                        record = json.loads(raw_bytes)
                        if record["model"] != model:
                            raise RuntimeError(f"Model mismatch: {path}")
                        identity = (
                            benchmark,
                            model,
                            record["task"],
                            int(record["generation_seed"]),
                            record["method"],
                        )
                        if identity in identities:
                            raise RuntimeError(f"Duplicate trajectory: {identity}")
                        identities.add(identity)
                        tasks.add((benchmark, record["task"]))
                        source_digest = sha256_bytes(raw_bytes)
                        source_hash.update("|".join(map(str, identity)).encode("utf-8"))
                        source_hash.update(b"\0" + source_digest.encode("ascii") + b"\n")
                        record["_artifact"] = {
                            "benchmark": benchmark,
                            "evidence_phase": evidence_phase,
                            "source_record_sha256": source_digest,
                        }
                        record = sanitize_json(record)
                        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                        stream.write("\n")
                        count += 1
    if count != EXPECTED[name]:
        raise RuntimeError(f"Expected {EXPECTED[name]} {name} records, found {count}")
    return {
        "path": destination.relative_to(OUT).as_posix(),
        "records": count,
        "task_instances": len(tasks),
        "compressed_bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "source_grid_sha256": source_hash.hexdigest(),
    }


def write_manifest() -> None:
    paths = sorted(
        path
        for path in OUT.rglob("*")
        if path.is_file()
        and path.name != "MANIFEST.sha256"
        and "reproduced" not in path.relative_to(OUT).parts
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )
    lines = [f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}" for path in paths]
    (OUT / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    copied = 0
    for relative in COPY_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = OUT / (relative[4:] if relative.startswith("FSE/") else relative)
        write_sanitized(source, destination)
        copied += 1
    for source, destination, suffixes in COPY_TREES:
        copied += copy_tree(source, destination, suffixes)

    licenses = OUT / "LICENSES"
    for benchmark in ("CWEval", "SALLM", "CodeGuardPlus"):
        write_sanitized(
            ROOT / "third_party" / benchmark / "LICENSE",
            licenses / f"{benchmark}-LICENSE",
        )

    primary = export_records("primary", PRIMARY_RUNS, "balanced-primary-20")
    legacy = export_records("legacy", LEGACY_RUNS, "legacy-support-31")
    index = {
        "schema_version": 1,
        "anonymous_review_artifact": True,
        "primary": primary,
        "legacy": legacy,
        "combined": {
            "records": primary["records"] + legacy["records"],
            "task_instances": primary["task_instances"] + legacy["task_instances"],
            "distinct_cwes": 24,
            "interpretation": "Primary is confirmatory; combined evidence is descriptive only.",
        },
    }
    (OUT / "data/index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_manifest()
    print(
        json.dumps(
            {
                "output": str(OUT),
                "copied_files_before_data": copied,
                "primary_records": primary["records"],
                "legacy_records": legacy["records"],
                "combined_records": index["combined"]["records"],
                "complete": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
