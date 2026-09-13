#!/usr/bin/env python3
"""Create a deterministic ZIP from the verified double-anonymous repository."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "FSE/anonymous-repository"
ARCHIVE = ROOT / "FSE/sectdd-fse-anonymous-artifact.zip"
CHECKSUM = ROOT / "FSE/sectdd-fse-anonymous-artifact.zip.sha256"
PREFIX = "sectdd-fse-anonymous-artifact"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    subprocess.run([sys.executable, str(SOURCE / "scripts/verify_artifact.py")], check=True)
    members = [SOURCE / "MANIFEST.sha256"]
    for line in (SOURCE / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        _, relative = line.split("  ", 1)
        members.append(SOURCE / relative)
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(members, key=lambda value: value.relative_to(SOURCE).as_posix()):
            relative = path.relative_to(SOURCE).as_posix()
            info = zipfile.ZipInfo(f"{PREFIX}/{relative}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix in {".sh", ".py"} else 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = sha256(ARCHIVE)
    CHECKSUM.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
    print(f"Archive: {ARCHIVE}")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
