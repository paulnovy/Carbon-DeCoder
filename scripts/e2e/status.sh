#!/usr/bin/env bash
# ============================================================
# E2E Test — Check Pipeline Status
# ============================================================
# Usage: bash scripts/e2e/status.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$PROJECT_DIR/tests/e2e-data"
STATE_FILE="$DATA_DIR/.state"
LOG_DIR="$DATA_DIR/logs"

echo "============================================"
echo "  WGS Cockpit — E2E Pipeline Status"
echo "============================================"
echo ""

# Data download
if [[ -f "$DATA_DIR/.download_done" ]]; then
  echo "✅ Data download: $(cat "$DATA_DIR/.download_done")"
else
  echo "❌ Data download: NOT DONE"
fi

# State
if [[ -f "$STATE_FILE" ]]; then
  source "$STATE_FILE"
  echo ""
  echo "Project: $PROJECT_ID"
  echo "Sample:  $SAMPLE_ID"
  echo "Run:     $RUN_ID"
  echo "API:     $API_BASE"
  echo ""
  
  # Steps
  steps=(
    "2:Create project"
    "3:Alignment"
    "4:Coverage"
    "5:Variant calling"
    "6:Normalization"
    "7:Taxonomy"
    "8:mtDNA"
    "9:SV calling"
    "10:CNV calling"
    "11:PRS scoring"
    "12:Reports"
  )
  
  for entry in "${steps[@]}"; do
    num="${entry%%:*}"
    desc="${entry#*:}"
    cp_file="$DATA_DIR/.step${num}_done"
    if [[ -f "$cp_file" ]]; then
      echo "  ✅ Step $num ($desc): $(cat "$cp_file")"
    else
      echo "  ⬜ Step $num ($desc): pending"
    fi
  done
  
  # Show latest logs
  echo ""
  echo "─── Latest logs ───"
  if [[ -d "$LOG_DIR" ]]; then
    ls -lt "$LOG_DIR"/*.log 2>/dev/null | head -5 || echo "  (none)"
  fi
  
  # API check
  echo ""
  echo "─── API Status ───"
  health=$(python3 << 'PYEOF'
import urllib.request, json
try:
    r = urllib.request.urlopen("http://localhost:8000/health", timeout=5)
    d = json.loads(r.read())
    print("healthy" if d["ok"] else "down")
except:
    print("unreachable")
PYEOF
)
  echo "  API: $health"
  
  # Show results
  if [[ -n "${RUN_ID:-}" ]]; then
    vars=$(python3 << PYEOF
import urllib.request, json
try:
    r = urllib.request.urlopen("${API_BASE:-http://localhost:8000}/samples/${SAMPLE_ID}/variants", timeout=10)
    print(len(json.loads(r.read())))
except:
    print("?")
PYEOF
)
    reports=$(python3 << PYEOF
import urllib.request, json
try:
    r = urllib.request.urlopen("${API_BASE:-http://localhost:8000}/runs/${RUN_ID}/reports", timeout=10)
    print(len(json.loads(r.read())))
except:
    print("?")
PYEOF
)
    echo "  Variants in API: $vars"
    echo "  Reports in API:  $reports"
  fi
else
  echo "❌ No state file — run 02_create_project.sh first"
fi

echo ""
echo "─── Disk usage ───"
du -sh "$DATA_DIR"/*/ 2>/dev/null || echo "  (no data directories)"
