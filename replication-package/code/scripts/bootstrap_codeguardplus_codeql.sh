#!/usr/bin/env bash
set -euo pipefail

sectdd_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sectdd_root="$(cd "${sectdd_script_dir}/.." && pwd)"
sectdd_version="2.17.5"
sectdd_install_root="${CODEGUARDPLUS_CODEQL_ROOT:-${sectdd_root}/.tools/codeguardplus}"
sectdd_cli_root="${sectdd_install_root}/codeql-cli-${sectdd_version}"
sectdd_query_root="${sectdd_install_root}/codeql-repo-${sectdd_version}"
sectdd_home="${sectdd_install_root}/home"
sectdd_archive_url="https://github.com/github/codeql-cli-binaries/releases/download/v${sectdd_version}/codeql-linux64.zip"
sectdd_query_url="https://github.com/github/codeql.git"
sectdd_query_tag="codeql-cli-${sectdd_version}"

mkdir -p "${sectdd_install_root}" "${sectdd_home}"

if [[ ! -x "${sectdd_cli_root}/codeql/codeql" ]]; then
  sectdd_temp="$(mktemp -d)"
  trap 'rm -rf -- "${sectdd_temp}"' EXIT
  curl -fL --retry 3 --output "${sectdd_temp}/codeql-linux64.zip" \
    "${sectdd_archive_url}"
  unzip -q "${sectdd_temp}/codeql-linux64.zip" -d "${sectdd_temp}/unpacked"
  test -x "${sectdd_temp}/unpacked/codeql/codeql"
  mkdir "${sectdd_cli_root}"
  mv "${sectdd_temp}/unpacked/codeql" "${sectdd_cli_root}/codeql"
  sha256sum "${sectdd_temp}/codeql-linux64.zip" \
    | awk '{print $1}' > "${sectdd_cli_root}/download.sha256"
  printf '%s\n' "${sectdd_archive_url}" > "${sectdd_cli_root}/download.url"
  rm -rf -- "${sectdd_temp}"
  trap - EXIT
fi

if [[ ! -d "${sectdd_query_root}/.git" ]]; then
  git clone --depth=1 --branch "${sectdd_query_tag}" \
    "${sectdd_query_url}" "${sectdd_query_root}"
fi

sectdd_codeql="${sectdd_cli_root}/codeql/codeql"
env HOME="${sectdd_home}" "${sectdd_codeql}" pack download \
  codeql-cpp@0.7.1 \
  codeql-python@0.6.2 \
  codeql/ssa@0.0.16 \
  codeql/tutorial@0.0.9 \
  codeql/regex@0.0.12 \
  codeql/util@0.0.9

"${sectdd_codeql}" version
"${sectdd_codeql}" resolve languages
git -C "${sectdd_query_root}" status --porcelain
echo "query_commit=$(git -C "${sectdd_query_root}" rev-parse HEAD)"
echo "CodeQL ready: ${sectdd_install_root}"
