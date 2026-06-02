#!/usr/bin/env bash
# ============================================================
# E2E Test — Create Project + Sample + Run via API
# ============================================================
# Usage: bash scripts/e2e/02_create_project.sh [API_BASE_URL]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_FILE="$PROJECT_DIR/tests/e2e-data/.state"
CHECKPOINT="$PROJECT_DIR/tests/e2e-data/.step2_done"

API="${1:-http://localhost:8000}"

echo "============================================"
echo "  WGS Cockpit — Create Project + Sample"
echo "============================================"
echo "API: $API"
echo ""

# Check if already done
if [[ -f "$CHECKPOINT" ]]; then
  echo "✅ Already done. Loading state..."
  source "$STATE_FILE"
  echo "  Project ID: $PROJECT_ID"
  echo "  Sample ID:  $SAMPLE_ID"
  echo "  Run ID:     $RUN_ID"
  exit 0
fi

# Source previous state if exists
[[ -f "$STATE_FILE" ]] && source "$STATE_FILE"

# ── Step 1: Verify API health ────────────────────────────────
echo "[1/5] Checking API health..."
health=$(python3 -c "
import urllib.request, json
r = urllib.request.urlopen('$API/health', timeout=10)
d = json.loads(r.read())
print(d['ok'])
" 2>/dev/null || echo "False")
if [[ "$health" != "True" ]]; then
  echo "❌ API not healthy at $API"
  exit 1
fi
echo "  ✅ API healthy"

# ── Step 2: Verify data is scannable ─────────────────────────
echo "[2/5] Scanning input directory..."
item_count=$(python3 -c "
import urllib.request, json
r = urllib.request.urlopen('$API/data/scan', timeout=10)
d = json.loads(r.read())
print(len(d.get('items', [])))
")
echo "  Found $item_count items in input directory"

# ── Step 3: Create project ───────────────────────────────────
echo "[3/5] Creating project..."
PROJECT_ID=$(python3 -c "
import urllib.request, json
data = json.dumps({'name': 'E2E Test chr20', 'description': 'End-to-end pipeline validation on GRCh38 chr20 simulated HG002 data'}).encode()
req = urllib.request.Request('$API/projects', data=data, headers={'Content-Type': 'application/json'}, method='POST')
r = urllib.request.urlopen(req, timeout=10)
print(json.loads(r.read())['id'])
")
echo "  ✅ Project: $PROJECT_ID"

# ── Step 4: Create sample ────────────────────────────────────
echo "[4/5] Creating sample..."
SAMPLE_ID=$(python3 -c "
import urllib.request, json
data = json.dumps({'sample_id': 'HG002_chr20', 'reference_id': 'GRCh38_standard'}).encode()
req = urllib.request.Request('$API/projects/$PROJECT_ID/samples', data=data, headers={'Content-Type': 'application/json'}, method='POST')
r = urllib.request.urlopen(req, timeout=10)
print(json.loads(r.read())['id'])
")
echo "  ✅ Sample: $SAMPLE_ID"

# ── Step 5: Create run ───────────────────────────────────────
echo "[5/5] Creating run..."
RUN_ID=$(python3 -c "
import urllib.request, json
data = json.dumps({'sample_id': '$SAMPLE_ID', 'reference_id': 'GRCh38_standard', 'mode': 'full'}).encode()
req = urllib.request.Request('$API/projects/$PROJECT_ID/run/qc', data=data, headers={'Content-Type': 'application/json'}, method='POST')
r = urllib.request.urlopen(req, timeout=10)
print(json.loads(r.read())['id'])
")
echo "  ✅ Run: $RUN_ID"

# ── Save state ───────────────────────────────────────────────
cat > "$STATE_FILE" <<EOF
PROJECT_ID="$PROJECT_ID"
SAMPLE_ID="$SAMPLE_ID"
RUN_ID="$RUN_ID"
API_BASE="$API"
CREATED_AT="$(date -Iseconds)"
EOF

echo "$(date -Iseconds)" > "$CHECKPOINT"

echo ""
echo "============================================"
echo "  ✅ Project structure created!"
echo "============================================"
echo "Project ID: $PROJECT_ID"
echo "Sample ID:  $SAMPLE_ID"
echo "Run ID:     $RUN_ID"
echo "State file: $STATE_FILE"
echo ""
echo "Next: bash scripts/e2e/03_run_pipeline.sh"
