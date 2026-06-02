#!/usr/bin/env bash
set -euo pipefail

OUTDIR="${OUTDIR:-results/local-pipeline-smoke}"
RUN_ID="${RUN_ID:-run_local_smoke}"
STRICT="${STRICT:-false}"
API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
LIVE_API="${LIVE_API:-false}"
THREADS="${THREADS:-1}"

ALLOW_FALLBACK="true"
if [[ "$STRICT" == "true" ]]; then
  ALLOW_FALLBACK="false"
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$OUTDIR"
WORKDIR="$(cd "$OUTDIR" && pwd)"

missing=()
if [[ "$STRICT" == "true" ]]; then
  for bin in bwa-mem2 samtools mosdepth bcftools; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      missing+=("$bin")
    fi
  done
  if ! command -v bgzip >/dev/null 2>&1 && ! command -v gzip >/dev/null 2>&1; then
    missing+=("bgzip_or_gzip")
  fi
  if [[ ${#missing[@]} -gt 0 ]]; then
    printf '[smoke] missing required tools for STRICT=true: %s\n' "${missing[*]}" >&2
    exit 127
  fi
fi

cd "$WORKDIR"

cat > ref.fa <<'FA'
>chr1
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
FA

cat > S_smoke_R1.fastq <<'FQ'
@S_smoke/1
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
+
IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII
FQ

cat > S_smoke_R2.fastq <<'FQ'
@S_smoke/2
ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT
+
IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIII
FQ

if command -v bwa-mem2 >/dev/null 2>&1; then
  bwa-mem2 index ref.fa >/dev/null 2>&1 || true
fi
if command -v samtools >/dev/null 2>&1; then
  samtools faidx ref.fa >/dev/null 2>&1 || true
fi

"$ROOT_DIR/pipelines/nextflow/scripts/run_alignment_stage.sh" \
  S_smoke ref.fa S_smoke_R1.fastq S_smoke_R2.fastq "$THREADS" "$ALLOW_FALLBACK"

"$ROOT_DIR/pipelines/nextflow/scripts/run_coverage_stage.sh" \
  S_smoke S_smoke.sorted.markdup.bam "$THREADS" 32 1mb "$ALLOW_FALLBACK"

"$ROOT_DIR/pipelines/nextflow/scripts/run_bcftools_variant_calling_stage.sh" \
  S_smoke S_smoke.sorted.markdup.bam ref.fa "$THREADS" "$ALLOW_FALLBACK"

"$ROOT_DIR/pipelines/nextflow/scripts/run_variant_normalization_stage.sh" \
  S_smoke S_smoke.bcftools.raw.vcf ref.fa "$ALLOW_FALLBACK"

python3 "$ROOT_DIR/pipelines/nextflow/scripts/post_ingest_contracts_batch.py" \
  --root "$WORKDIR" \
  --run-id "$RUN_ID" \
  --api-base-url "$API_BASE_URL" \
  --absolutize-payload-paths \
  --dry-run \
  --output smoke.ingest.batch.dry_run.json >/dev/null

live_summary_json=null
if [[ "$LIVE_API" == "true" ]]; then
  python3 "$ROOT_DIR/scripts/post_local_pipeline_smoke_live.py" \
    --outdir "$WORKDIR" \
    --api-base-url "$API_BASE_URL" \
    --project-name "Local Pipeline Smoke" \
    --sample-id "S_local_smoke" \
    --reference-id "GRCh38_standard"
  live_summary_json='"smoke.live_api.summary.json"'
fi

cat > smoke.summary.json <<JSON
{
  "ok": true,
  "strict": ${STRICT},
  "allow_fallback": ${ALLOW_FALLBACK},
  "live_api": ${LIVE_API},
  "run_id": "${RUN_ID}",
  "outdir": "${WORKDIR}",
  "artifacts": {
    "alignment_contract": "S_smoke.alignment.ingest.json",
    "coverage_contract": "S_smoke.coverage.ingest.json",
    "variant_calling_contract": "S_smoke.variants.bcftools.ingest.json",
    "variant_normalization_contract": "S_smoke.variants.ingest.json",
    "batch_dry_run": "smoke.ingest.batch.dry_run.json",
    "live_api_summary": ${live_summary_json}
  }
}
JSON

printf '[smoke] ok; summary=%s\n' "$WORKDIR/smoke.summary.json"
