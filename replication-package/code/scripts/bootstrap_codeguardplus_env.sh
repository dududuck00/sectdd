#!/usr/bin/env bash
set -euo pipefail

sectdd_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sectdd_root="$(cd "${sectdd_script_dir}/.." && pwd)"
sectdd_system_python="${CODEGUARDPLUS_SYSTEM_PYTHON:-/usr/bin/python3.10}"
sectdd_env_root="${CODEGUARDPLUS_ENV_ROOT:-${sectdd_root}/.venv-codeguardplus}"
sectdd_env_python="${sectdd_env_root}/bin/python"
sectdd_lock="${sectdd_root}/requirements/codeguardplus-audit-v1-lock.txt"

if [[ ! -x "${sectdd_system_python}" ]]; then
  echo "Python 3.10 not found: ${sectdd_system_python}" >&2
  exit 1
fi
if [[ ! -f "${sectdd_lock}" ]]; then
  echo "Dependency lock not found: ${sectdd_lock}" >&2
  exit 1
fi

if [[ ! -x "${sectdd_env_python}" ]]; then
  # Ubuntu may omit ensurepip while still creating a usable isolated prefix.
  "${sectdd_system_python}" -m venv "${sectdd_env_root}" || true
fi
if [[ ! -x "${sectdd_env_python}" ]]; then
  echo "Could not create ${sectdd_env_root}" >&2
  exit 1
fi

sectdd_site_packages="$(
  "${sectdd_env_python}" -c \
    'import sysconfig; print(sysconfig.get_paths()["purelib"])'
)"

sectdd_probe='import argon2,boto3,Crypto,cryptography,defusedxml,django,flask,func_timeout,jinja2,jose,jwt,libcst,lxml,paramiko,yaml'
if ! "${sectdd_env_python}" - "${sectdd_lock}" >/dev/null 2>&1 <<'PY'
import re
import sys
from importlib.metadata import PackageNotFoundError, version

for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    match = re.fullmatch(r"([^=]+)==(.+)", line)
    if not match:
        raise SystemExit(f"Unpinned requirement: {line}")
    name, expected = match.groups()
    try:
        observed = version(name)
    except PackageNotFoundError:
        raise SystemExit(f"Missing package: {name}")
    if observed != expected:
        raise SystemExit(f"Version mismatch: {name} {observed} != {expected}")
PY
then
  "${sectdd_system_python}" -m pip install \
    --upgrade \
    --ignore-installed \
    --target "${sectdd_site_packages}" \
    -r "${sectdd_lock}"
fi

"${sectdd_env_python}" -c "${sectdd_probe}"
"${sectdd_env_python}" - "${sectdd_lock}" <<'PY'
import re
import sys
from importlib.metadata import version

for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if line and not line.startswith("#"):
        name, expected = re.fullmatch(r"([^=]+)==(.+)", line).groups()
        assert version(name) == expected, (name, version(name), expected)
PY
"${sectdd_env_python}" - <<'PY'
import hashlib
import json
import sqlite3
import sys
from importlib.metadata import distributions

packages = sorted(
    f"{d.metadata.get('Name', 'UNKNOWN')}=={d.version}"
    for d in distributions()
)
payload = {
    "python": sys.version,
    "sqlite_version": sqlite3.sqlite_version,
    "installed_distributions_sha256": hashlib.sha256(
        ("\n".join(packages) + "\n").encode()
    ).hexdigest(),
}
print(json.dumps(payload, indent=2))
PY

echo "CodeGuard+ Python environment ready: ${sectdd_env_root}"
