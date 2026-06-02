#!/usr/bin/env bash
set -euo pipefail

# GIAB / vendor benchmark stage.
# Usage: run_benchmark_stage.sh <sample_id> <query_vcf> <reference_fasta> <threads> <allow_dev_fallback>
#
# Required configuration:
# - WGS_BENCHMARK_TRUTH_VCF=/path/truth.vcf.gz
# Optional:
# - WGS_BENCHMARK_TRUTH_BED=/path/high-confidence.bed
# - WGS_BENCHMARK_MODE=auto|happy|truvari

sample_id="$1"
query_vcf="$2"
reference_fasta="$3"
threads="${4:-4}"
allow_dev_fallback="${5:-false}"

truth_vcf="${WGS_BENCHMARK_TRUTH_VCF:-}"
truth_bed="${WGS_BENCHMARK_TRUTH_BED:-}"
mode="${WGS_BENCHMARK_MODE:-auto}"
out_prefix="${sample_id}.benchmark"
happy_prefix="${out_prefix}.happy"
truvari_dir="${out_prefix}.truvari"
ingest="${sample_id}.benchmark.ingest.json"

if [[ -z "$truth_vcf" || ! -s "$truth_vcf" ]]; then
  echo "[benchmark] truth VCF is not configured; set WGS_BENCHMARK_TRUTH_VCF" >&2
  exit 127
fi
if [[ ! -s "$query_vcf" ]]; then
  echo "[benchmark] query VCF not found: ${query_vcf}" >&2
  exit 2
fi

have_happy=false
if command -v hap.py >/dev/null 2>&1 || command -v happy >/dev/null 2>&1; then
  have_happy=true
fi
have_truvari=false
if command -v truvari >/dev/null 2>&1; then
  have_truvari=true
fi

benchmark_report=""
benchmark_mode=""

if [[ "$mode" == "auto" || "$mode" == "happy" ]]; then
  if [[ "$have_happy" == "true" ]]; then
    happy_bin="$(command -v hap.py || command -v happy)"
    cmd=("$happy_bin" "$truth_vcf" "$query_vcf" -r "$reference_fasta" -o "$happy_prefix" --threads "$threads")
    if [[ -n "$truth_bed" && -s "$truth_bed" ]]; then
      cmd+=(-f "$truth_bed")
    fi
    echo "[benchmark] running hap.py for ${sample_id}" >&2
    "${cmd[@]}"
    benchmark_report="${happy_prefix}.summary.csv"
    benchmark_mode="happy"
  elif [[ "$mode" == "happy" ]]; then
    echo "[benchmark] hap.py/happy is not installed" >&2
    exit 127
  fi
fi

if [[ -z "$benchmark_report" && ( "$mode" == "auto" || "$mode" == "truvari" ) ]]; then
  if [[ "$have_truvari" == "true" ]]; then
    echo "[benchmark] running Truvari for ${sample_id}" >&2
    truvari bench -b "$truth_vcf" -c "$query_vcf" -f "$reference_fasta" -o "$truvari_dir"
    benchmark_report="${truvari_dir}/summary.json"
    benchmark_mode="truvari"
  elif [[ "$mode" == "truvari" ]]; then
    echo "[benchmark] truvari is not installed" >&2
    exit 127
  fi
fi

if [[ -z "$benchmark_report" || ! -s "$benchmark_report" ]]; then
  echo "[benchmark] no benchmark tool available; allow_dev_fallback=${allow_dev_fallback}; no synthetic benchmark emitted" >&2
  exit 127
fi

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "benchmark",
  "payload": {
    "benchmark_id": "${sample_id}_${benchmark_mode}",
    "benchmark_report_path": "${benchmark_report}",
    "benchmark_mode": "${benchmark_mode}",
    "truth_vcf_path": "${truth_vcf}",
    "truth_bed_path": "${truth_bed}",
    "query_vcf_path": "${query_vcf}",
    "source_files": ["${benchmark_report}", "${truth_vcf}", "${truth_bed}", "${query_vcf}"]
  }
}
JSON
