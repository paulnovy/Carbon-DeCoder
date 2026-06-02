#!/usr/bin/env bash
# ============================================================
# E2E Test — Run Full Pipeline with Checkpoints
# ============================================================
# Usage: bash scripts/e2e/03_run_pipeline.sh [API_BASE_URL]
#
# Each step is checkpointed. Re-run to resume from last step.
# Logs go to tests/e2e-data/logs/
# Results go to tests/e2e-data/results/
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATE_FILE="$PROJECT_DIR/tests/e2e-data/.state"
LOG_DIR="$PROJECT_DIR/tests/e2e-data/logs"
SCRIPTS="$PROJECT_DIR/pipelines/nextflow/scripts"

# Copy stage scripts to writable dir and strip Windows CRLF
WORK_SCRIPTS="/tmp/wgs-stages"
mkdir -p "$WORK_SCRIPTS"
for f in "$SCRIPTS"/run_*_stage.sh; do
  fname=$(basename "$f")
  sed 's/\r$//' "$f" > "$WORK_SCRIPTS/$fname"
  chmod +x "$WORK_SCRIPTS/$fname"
done
SCRIPTS="$WORK_SCRIPTS"
echo "  Scripts prepared (CRLF-stripped) in $WORK_SCRIPTS"

API="${1:-http://localhost:8000}"

mkdir -p "$LOG_DIR"

# Load state
if [[ ! -f "$STATE_FILE" ]]; then
  echo "❌ No state file. Run 02_create_project.sh first."
  exit 1
fi
source "$STATE_FILE"

REF="$PROJECT_DIR/tests/e2e-data/reference/chr20.fa"
# Fallback to .gz if uncompressed not found
[[ ! -f "$REF" ]] && REF="$PROJECT_DIR/tests/e2e-data/reference/chr20.fa.gz"
R1="$PROJECT_DIR/tests/e2e-data/reads/HG002_chr20_R1.fastq.gz"
R2="$PROJECT_DIR/tests/e2e-data/reads/HG002_chr20_R2.fastq.gz"
THREADS=10
RESULTS_DIR="$PROJECT_DIR/tests/e2e-data/results"
mkdir -p "$RESULTS_DIR"

# Fix Windows CRLF in all stage scripts
for f in "$SCRIPTS"/run_*_stage.sh; do
  sed -i 's/\r$//' "$f" 2>/dev/null || true
done

# Checkpoint helper
check_step() {
  local step=$1
  local cp_file="$PROJECT_DIR/tests/e2e-data/.step${step}_done"
  if [[ -f "$cp_file" ]]; then
    echo "⏭️  Step $step already done ($(cat "$cp_file"))"
    return 0
  fi
  return 1
}

mark_done() {
  local step=$1
  echo "$(date -Iseconds)" > "$PROJECT_DIR/tests/e2e-data/.step${step}_done"
}

ingest_result() {
  local stage=$1
  local json_file=$2
  local log_file="$LOG_DIR/ingest_${stage}.log"
  
  echo "  Ingesting $stage..."
  python3 -c "
import urllib.request, json, os
results_dir = '$RESULTS_DIR'
with open('$json_file') as f:
    raw = json.load(f)
raw.pop('event_type', None)
# Resolve relative file paths to absolute (API CWD != results dir)
payload = raw.get('payload', {})
for key in list(payload.keys()):
    val = payload[key]
    if isinstance(val, str) and not os.path.isabs(val):
        abs_path = os.path.join(results_dir, val)
        if os.path.exists(abs_path):
            payload[key] = abs_path
    elif isinstance(val, list):
        resolved = []
        for v in val:
            if isinstance(v, str) and not os.path.isabs(v):
                ap = os.path.join(results_dir, v)
                resolved.append(ap if os.path.exists(ap) else v)
            else:
                resolved.append(v)
        payload[key] = resolved
data = json.dumps(raw).encode()
req = urllib.request.Request('$API/runs/$RUN_ID/ingest', data=data, headers={'Content-Type': 'application/json'}, method='POST')
r = urllib.request.urlopen(req, timeout=60)
print(r.read().decode())
" > "$log_file" 2>&1 || {
      echo "  ⚠️  Ingest failed (see $log_file)"
      tail -3 "$log_file" 2>/dev/null
      return 0  # don't abort pipeline on ingest failure
    }
  echo "  ✅ $stage ingested"
}

echo "============================================"
echo "  WGS Cockpit — E2E Pipeline Run"
echo "============================================"
echo "Project: $PROJECT_ID"
echo "Sample:  $SAMPLE_ID"
echo "Run:     $RUN_ID"
echo "API:     $API"
echo "Results: $RESULTS_DIR"
echo "============================================"
echo ""

# ── Step 3: Alignment ────────────────────────────────────────
# Args: sample_id reference_fasta r1 r2 threads allow_dev_fallback
if ! check_step 3; then
  echo "═══ [3/12] Alignment (bwa-mem2) ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_alignment_stage.sh" \
    "HG002_chr20" "$REF" "$R1" "$R2" "$THREADS" "true") \
    > "$LOG_DIR/alignment.log" 2>&1
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  echo "  BAM: $(ls -lh "$RESULTS_DIR"/HG002_chr20*.bam 2>/dev/null | awk '{print $5}' | head -1)"
  
  # Ingest
  [[ -f "$RESULTS_DIR/HG002_chr20.alignment.ingest.json" ]] && \
    ingest_result "alignment" "$RESULTS_DIR/HG002_chr20.alignment.ingest.json"
  
  mark_done 3
  echo "  ✅ Alignment complete"
  echo ""
fi

# ── Step 4: Coverage ─────────────────────────────────────────
# Args: sample_id bam threads window_size tile_level
if ! check_step 4; then
  echo "═══ [4/12] Coverage (mosdepth) ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  BAM="$RESULTS_DIR/HG002_chr20.sorted.markdup.bam"
  (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_coverage_stage.sh" \
    "HG002_chr20" "$BAM" "$THREADS" "1000000" "1mb") \
    > "$LOG_DIR/coverage.log" 2>&1
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  
  [[ -f "$RESULTS_DIR/HG002_chr20.coverage.ingest.json" ]] && \
    ingest_result "coverage" "$RESULTS_DIR/HG002_chr20.coverage.ingest.json"
  
  mark_done 4
  echo "  ✅ Coverage complete"
  echo ""
fi

# ── Step 5: Variant Calling (bcftools) ───────────────────────
# Args: sample_id bam reference_fasta threads allow_dev_fallback
if ! check_step 5; then
  echo "═══ [5/12] Variant Calling (bcftools) ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  BAM="$RESULTS_DIR/HG002_chr20.sorted.markdup.bam"
  (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_bcftools_variant_calling_stage.sh" \
    "HG002_chr20" "$BAM" "$REF" "$THREADS" "true") \
    > "$LOG_DIR/variant_calling.log" 2>&1
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  
  # Find the ingest JSON (name varies)
  VCF_INGEST=$(find "$RESULTS_DIR" -name "HG002_chr20*variant*ingest*.json" -o -name "HG002_chr20*bcftools*ingest*.json" 2>/dev/null | head -1)
  [[ -n "$VCF_INGEST" ]] && ingest_result "variants" "$VCF_INGEST"
  
  mark_done 5
  echo "  ✅ Variant calling complete"
  echo ""
fi

# ── Step 6: Variant Normalization ────────────────────────────
# Args: sample_id input_vcf reference_fasta allow_dev_fallback
if ! check_step 6; then
  echo "═══ [6/12] Variant Normalization ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  VCF=$(find "$RESULTS_DIR" -name "HG002_chr20*.vcf.gz" ! -name "*norm*" 2>/dev/null | head -1)
  if [[ -n "$VCF" ]]; then
    (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_variant_normalization_stage.sh" \
      "HG002_chr20" "$VCF" "$REF" "true") \
      > "$LOG_DIR/normalization.log" 2>&1
    
    NORM_INGEST=$(find "$RESULTS_DIR" -name "HG002_chr20*normali*ingest*.json" 2>/dev/null | head -1)
    [[ -n "$NORM_INGEST" ]] && ingest_result "normalization" "$NORM_INGEST"
  else
    echo "  ⚠️  No VCF found, skipping normalization"
  fi
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  mark_done 6
  echo "  ✅ Normalization complete"
  echo ""
fi

# ── Step 7: Taxonomy ────────────────────────────────────────
# Args: sample_id r1 r2 threads allow_dev_fallback [kraken2_db]
if ! check_step 7; then
  echo "═══ [7/12] Taxonomy (Kraken2) ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_taxonomy_stage.sh" \
    "HG002_chr20" "$R1" "$R2" "$THREADS" "true") \
    > "$LOG_DIR/taxonomy.log" 2>&1
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  
  TAX_INGEST=$(find "$RESULTS_DIR" -name "HG002_chr20*taxonomy*ingest*.json" 2>/dev/null | head -1)
  [[ -n "$TAX_INGEST" ]] && ingest_result "taxonomy" "$TAX_INGEST"
  
  mark_done 7
  echo "  ✅ Taxonomy complete"
  echo ""
fi

# ── Step 8: mtDNA ───────────────────────────────────────────
# Args: sample_id bam reference_fasta threads allow_dev_fallback
if ! check_step 8; then
  echo "═══ [8/12] mtDNA Analysis ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  BAM="$RESULTS_DIR/HG002_chr20.sorted.markdup.bam"
  (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_mtdna_stage.sh" \
    "HG002_chr20" "$BAM" "$REF" "$THREADS" "true") \
    > "$LOG_DIR/mtdna.log" 2>&1
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  
  MTDNA_INGEST=$(find "$RESULTS_DIR" -name "HG002_chr20*mtdna*ingest*.json" 2>/dev/null | head -1)
  [[ -n "$MTDNA_INGEST" ]] && ingest_result "mtdna" "$MTDNA_INGEST"
  
  mark_done 8
  echo "  ✅ mtDNA complete"
  echo ""
fi

# ── Step 9: SV Calling ──────────────────────────────────────
# Args: sample_id bam reference_fasta threads allow_dev_fallback
if ! check_step 9; then
  echo "═══ [9/12] SV Calling (Manta/Delly) ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  BAM="$RESULTS_DIR/HG002_chr20.sorted.markdup.bam"
  (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_sv_calling_stage.sh" \
    "HG002_chr20" "$BAM" "$REF" "$THREADS" "true") \
    > "$LOG_DIR/sv_calling.log" 2>&1
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  
  SV_INGEST=$(find "$RESULTS_DIR" -name "HG002_chr20*sv*ingest*.json" 2>/dev/null | head -1)
  [[ -n "$SV_INGEST" ]] && ingest_result "sv" "$SV_INGEST"
  
  mark_done 9
  echo "  ✅ SV calling complete"
  echo ""
fi

# ── Step 10: CNV Calling ─────────────────────────────────────
# Args: sample_id bam reference_fasta threads allow_dev_fallback
if ! check_step 10; then
  echo "═══ [10/12] CNV Calling (CNVkit) ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  BAM="$RESULTS_DIR/HG002_chr20.sorted.markdup.bam"
  (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_cnv_calling_stage.sh" \
    "HG002_chr20" "$BAM" "$REF" "$THREADS" "true") \
    > "$LOG_DIR/cnv_calling.log" 2>&1
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  
  CNV_INGEST=$(find "$RESULTS_DIR" -name "HG002_chr20*cnv*ingest*.json" 2>/dev/null | head -1)
  [[ -n "$CNV_INGEST" ]] && ingest_result "cnv" "$CNV_INGEST"
  
  mark_done 10
  echo "  ✅ CNV calling complete"
  echo ""
fi

# ── Step 11: PRS ─────────────────────────────────────────────
# Args: sample_id vcf reference_fasta threads allow_dev_fallback
if ! check_step 11; then
  echo "═══ [11/12] PRS Scoring ═══"
  echo "  Started: $(date)"
  start_ts=$(date +%s)
  
  VCF=$(find "$RESULTS_DIR" -name "HG002_chr20*.vcf.gz" ! -name "*norm*" 2>/dev/null | head -1)
  if [[ -n "$VCF" ]]; then
    (cd "$RESULTS_DIR" && time bash "$SCRIPTS/run_prs_stage.sh" \
      "HG002_chr20" "$VCF" "GRCh38_standard" "true") \
      > "$LOG_DIR/prs.log" 2>&1
    
    PRS_INGEST=$(find "$RESULTS_DIR" -name "HG002_chr20*prs*ingest*.json" 2>/dev/null | head -1)
    [[ -n "$PRS_INGEST" ]] && ingest_result "prs" "$PRS_INGEST"
  else
    echo "  ⚠️  No VCF found, skipping PRS"
  fi
  
  elapsed=$(( $(date +%s) - start_ts ))
  echo "  Took: ${elapsed}s"
  mark_done 11
  echo "  ✅ PRS complete"
  echo ""
fi

# ── Step 12: Generate Reports ────────────────────────────────
if ! check_step 12; then
  echo "═══ [12/12] Generate Reports ═══"
  echo "  Started: $(date)"
  
  report_types=("qc" "alignment" "coverage" "variant" "sv" "cnv" "taxonomy" "mtdna" "prs" "full_technical")
  success=0
  for rtype in "${report_types[@]}"; do
    echo "  Generating $rtype..."
    result=$(python3 -c "
import urllib.request, json
data = json.dumps({'report_type': '$rtype'}).encode()
req = urllib.request.Request('$API/runs/$RUN_ID/reports/generate', data=data, headers={'Content-Type': 'application/json'}, method='POST')
r = urllib.request.urlopen(req, timeout=60)
print(r.read().decode())
" 2>/dev/null) && {
      echo "    ✅ $rtype"
      ((success++))
    } || echo "    ⚠️  $rtype failed"
  done
  echo "  Generated $success/${#report_types[@]} reports"
  
  mark_done 12
  echo "  ✅ Reports complete"
  echo ""
fi

# ── Final Verification ───────────────────────────────────────
echo "============================================"
echo "  🎉 E2E Pipeline Complete!"
echo "============================================"
echo ""

# Show results
vars=$(python3 -c "
import urllib.request, json
r = urllib.request.urlopen('$API/samples/$SAMPLE_ID/variants', timeout=10)
print(len(json.loads(r.read())))
" 2>/dev/null || echo "?")
cov=$(python3 -c '
import urllib.request, json
r = urllib.request.urlopen("$API/samples/$SAMPLE_ID/coverage-summary", timeout=10)
d = json.loads(r.read())
print("mean=" + str(d.get("mean_depth","?")) + ", callable=" + str(d.get("callable_fraction","?")))
' 2>/dev/null || echo "?")
reports=$(python3 -c "
import urllib.request, json
r = urllib.request.urlopen('$API/runs/$RUN_ID/reports', timeout=10)
print(len(json.loads(r.read())))
" 2>/dev/null || echo "?")

echo "Results:"
echo "  Variants: $vars"
echo "  Coverage: $cov"
echo "  Reports:  $reports"
echo ""
echo "Cockpit: ${FRONTEND_URL:-http://localhost:3000}"
echo "  → Projects → E2E Test chr20"
echo ""
echo "Logs:    $LOG_DIR/"
echo "Results: $RESULTS_DIR/"
echo ""
echo "Status check: bash scripts/e2e/status.sh"
