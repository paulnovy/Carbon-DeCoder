#!/usr/bin/env bash
set -euo pipefail

# PRS (Polygenic Risk Score) stage.
# Research-only, non-diagnostic.
# Usage: run_prs_stage.sh <sample_id> <input_vcf> <reference_id> <allow_dev_fallback>
#
# This stage never emits synthetic/demo scores. It runs pgsc_calc only when
# explicitly enabled/configured, then converts pgsc_calc output to the WGS
# Cockpit ingest contract.

sample_id="$1"
input_vcf="$2"
reference_id="${3:-GRCh38_standard}"
allow_dev_fallback="${4:-false}"

prs_result="${sample_id}.prs.result.txt"
ingest="${sample_id}.prs.ingest.json"
samplesheet="${sample_id}.pgsc_calc.samplesheet.csv"
pgsc_outdir="${WGS_PGSC_CALC_OUTDIR:-${PWD}/${sample_id}.pgsc_calc}"

enabled="${WGS_PGSC_CALC_ENABLED:-false}"
pgs_ids="${WGS_PGSC_CALC_PGS_IDS:-}"
scorefile="${WGS_PGSC_CALC_SCOREFILE:-}"
profile="${WGS_PGSC_CALC_PROFILE:-}"
revision="${WGS_PGSC_CALC_REVISION:-}"
target_build="${WGS_PGSC_CALC_TARGET_BUILD:-}"
samplesheet_override="${WGS_PGSC_CALC_SAMPLESHEET:-}"
extra_args="${WGS_PGSC_CALC_EXTRA_ARGS:-}"

fail_unconfigured() {
  echo "[prs] curated PRS panel is not configured for ${sample_id}" >&2
  echo "[prs] pgsc_calc is not configured for ${sample_id}" >&2
  echo "[prs] set WGS_PGSC_CALC_ENABLED=true plus WGS_PGSC_CALC_PGS_IDS or WGS_PGSC_CALC_SCOREFILE" >&2
  echo "[prs] no synthetic fallback is emitted by policy (allow_dev_fallback=${allow_dev_fallback})" >&2
  exit 127
}

if [[ "$enabled" != "true" ]]; then
  fail_unconfigured
fi

if ! command -v nextflow >/dev/null 2>&1; then
  echo "[prs] nextflow is required for pgsc_calc" >&2
  exit 127
fi

if [[ ! -s "$input_vcf" ]]; then
  echo "[prs] input VCF not found: ${input_vcf}" >&2
  exit 2
fi

if [[ -z "$pgs_ids" && -z "$scorefile" ]]; then
  fail_unconfigured
fi

if [[ -z "$target_build" ]]; then
  case "$reference_id" in
    *37*|*hg19*|*GRCh37*) target_build="GRCh37" ;;
    *) target_build="GRCh38" ;;
  esac
fi

if [[ -n "$samplesheet_override" ]]; then
  samplesheet="$samplesheet_override"
else
  cat > "$samplesheet" <<CSV
sampleset,path_prefix,chrom,format
${sample_id},${input_vcf},,vcf
CSV
fi

cmd=(nextflow run pgscatalog/pgsc_calc)
if [[ -n "$revision" ]]; then
  cmd+=(-r "$revision")
fi
if [[ -n "$profile" ]]; then
  cmd+=(-profile "$profile")
fi
cmd+=(--input "$samplesheet" --target_build "$target_build" --outdir "$pgsc_outdir")
if [[ -n "$pgs_ids" ]]; then
  cmd+=(--pgs_id "$pgs_ids")
fi
if [[ -n "$scorefile" ]]; then
  cmd+=(--scorefile "$scorefile")
fi
if [[ -n "$extra_args" ]]; then
  # shellcheck disable=SC2206
  extra_parts=($extra_args)
  cmd+=("${extra_parts[@]}")
fi

echo "[prs] running pgsc_calc for ${sample_id}" >&2
printf '[prs] command:' >&2
printf ' %q' "${cmd[@]}" >&2
printf '\n' >&2
"${cmd[@]}"

scores_path="$(find "$pgsc_outdir" -path '*/score/*_pgs.txt.gz' -o -path '*/score/aggregated_scores.txt.gz' -o -name 'scores.txt.gz' | sort | head -n 1)"
summary_path="$(find "$pgsc_outdir" -path '*/match/*_summary.csv' | sort | head -n 1 || true)"
if [[ -z "$scores_path" || ! -s "$scores_path" ]]; then
  echo "[prs] pgsc_calc finished but score output was not found under ${pgsc_outdir}" >&2
  exit 3
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$script_dir/parse_pgscalc_output.py" \
  --scores "$scores_path" \
  ${summary_path:+--summary "$summary_path"} \
  --out "$prs_result"

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "prs",
  "payload": {
    "prs_result_path": "${prs_result}",
    "source_files": ["${prs_result}", "${scores_path}", "${summary_path}"],
    "prs_mode": "pgsc_calc",
    "pgsc_calc_outdir": "${pgsc_outdir}",
    "pgsc_calc_target_build": "${target_build}",
    "pgsc_calc_pgs_ids": "${pgs_ids}",
    "pgsc_calc_scorefile": "${scorefile}"
  }
}
JSON
