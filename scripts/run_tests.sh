#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
TEST_VENV="${WGS_TEST_VENV:-.venv-test}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -x "$TEST_VENV/bin/python" ]]; then
  PYTHON_BIN="$TEST_VENV/bin/python"
fi

if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import fastapi, pydantic, pytest
PY
then
  echo "[tests] Bootstrapping test venv at ${TEST_VENV}"
  "${PYTHON_BIN:-python3}" -m venv "$TEST_VENV"
  "$TEST_VENV/bin/python" -m pip install --upgrade pip
  "$TEST_VENV/bin/python" -m pip install -e 'apps/api[dev]'
  PYTHON_BIN="$TEST_VENV/bin/python"
else
  echo "[tests] Using Python environment: ${PYTHON_BIN}"
fi

PYTEST_BIN="$($PYTHON_BIN - <<'PY'
import shutil, sys
candidate = shutil.which('pytest')
print(candidate or sys.executable + ' -m pytest')
PY
)"

echo "[tests] Python: $($PYTHON_BIN --version 2>&1)"
echo "[tests] Pytest: $($PYTHON_BIN -m pytest --version 2>&1)"

echo "[tests] API suite"
PYTHONPATH=apps/api:. "$PYTHON_BIN" -m pytest -q apps/api/tests

if [[ -f apps/frontend/package.json ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm not found; cannot run frontend gate" >&2
    exit 127
  fi
  echo "[tests] Frontend suite"
  npm ci --prefix apps/frontend --no-audit --no-fund
  NEXT_TELEMETRY_DISABLED=1 npm test --prefix apps/frontend
fi
