#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SYSTEM_PYTHON="${SALLM_SYSTEM_PYTHON:-/usr/bin/python3.10}"
ENV_ROOT="${SALLM_ENV_ROOT:-${PROJECT_ROOT}/.venv-sallm}"
ENV_PYTHON="${ENV_ROOT}/bin/python"

if [[ ! -x "${SYSTEM_PYTHON}" ]]; then
  echo "Python 3.10 not found: ${SYSTEM_PYTHON}" >&2
  exit 1
fi

if [[ ! -x "${ENV_PYTHON}" ]]; then
  # Ubuntu may return non-zero because ensurepip/python3.10-venv is absent,
  # while still creating a valid isolated interpreter and pyvenv.cfg.
  "${SYSTEM_PYTHON}" -m venv "${ENV_ROOT}" || true
fi

if [[ ! -x "${ENV_PYTHON}" ]]; then
  echo "Could not create the isolated interpreter at ${ENV_PYTHON}" >&2
  exit 1
fi

SITE_PACKAGES="$(
  "${ENV_PYTHON}" -c \
    'import sysconfig; print(sysconfig.get_paths()["purelib"])'
)"

if "${ENV_PYTHON}" -c \
  'import flask, flask_sqlalchemy, Crypto, requests, canvasapi, lxml, jwt, paramiko, django' \
  >/dev/null 2>&1; then
  echo "SALLM Python environment is already ready: ${ENV_ROOT}"
  exit 0
fi

echo "Installing SALLM packages into ${SITE_PACKAGES}"
"${SYSTEM_PYTHON}" -m pip install \
  --upgrade \
  --ignore-installed \
  --target "${SITE_PACKAGES}" \
  -r "${PROJECT_ROOT}/requirements/sallm-audit-overlay-v1-lock.txt"

"${ENV_PYTHON}" -c \
  'import flask, flask_sqlalchemy, Crypto, requests, canvasapi, lxml, jwt, paramiko, django'

echo "SALLM Python environment is ready: ${ENV_ROOT}"
