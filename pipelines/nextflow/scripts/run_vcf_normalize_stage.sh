#!/usr/bin/env bash
set -euo pipefail

# WGS Cockpit — VCF Normalization Stage
# Runs bcftools norm for left-alignment and splitting of multi-allelic records.
# Usage: run_vcf_normalize_stage.sh <sample_id> <input_vcf_or_bam> <reference_fasta> <threads> <allow_dev_fallback>

sample_id="$1"
input_path="$2"
reference_fasta="$3"
threads="${4:-4}"
allow_dev_fallback="${5:-true}"

normalized_vcf="${sample_id}.variants.normalized.vcf"
normalized_vcf_gz="${normalized_vcf}.gz"
stats_file="${normalized_vcf}.stats"
ingest="${sample_id}.normalize.ingest.json"

if [[ ! -s "$input_path" ]]; then
  echo "[normalize] input file not found or empty: ${input_path}" >&2
  exit 2
fi

have_bcftools=false
if command -v bcftools >/dev/null 2>&1; then
  have_bcftools=true
fi

have_bgzip=false
if command -v bgzip >/dev/null 2>&1; then
  have_bgzip=true
fi

have_tabix=false
if command -v tabix >/dev/null 2>&1; then
  have_tabix=true
fi

normalization_mode="unknown"

# If input is BAM, convert to VCF first using bcftools mpileup + call
input_vcf="$input_path"
if [[ "$input_path" == *.bam || "$input_path" == *.cram ]]; then
  if [[ "$have_bcftools" == "true" ]]; then
    echo "[normalize] converting BAM/CRAM to VCF via bcftools mpileup+call" >&2
    raw_vcf="${sample_id}.variants.raw.vcf"
    if [[ -s "$reference_fasta" ]]; then
      bcftools mpileup -f "$reference_fasta" --threads "$threads" "$input_path" \
        | bcftools call -mv -Ov -o "$raw_vcf" --threads "$threads"
    else
      echo "[normalize] reference FASTA required for BAM→VCF conversion" >&2
      exit 2
    fi
    input_vcf="$raw_vcf"
  else
    echo "[normalize] bcftools required for BAM/CRAM input" >&2
    exit 127
  fi
fi

if [[ "$have_bcftools" == "true" ]]; then
  echo "[normalize] running bcftools norm for ${sample_id}" >&2
  norm_ok=false
  if [[ -s "$reference_fasta" ]]; then
    # Full normalization: split multi-allelic + left-align against reference
    if bcftools norm -m -any -f "$reference_fasta" --threads "$threads" "$input_vcf" -Ov -o "$normalized_vcf" 2>norm.stderr; then
      normalization_mode="bcftools_norm_ref_aligned"
      norm_ok=true
    fi
  fi
  if [[ "$norm_ok" != "true" ]]; then
    # Fallback: split multi-allelic without left-alignment
    if bcftools norm -m -any --threads "$threads" "$input_vcf" -Ov -o "$normalized_vcf" 2>norm.stderr; then
      normalization_mode="bcftools_norm_split_only"
      norm_ok=true
    fi
  fi
  if [[ "$norm_ok" != "true" ]]; then
    echo "[normalize] bcftools norm failed, falling back to copy" >&2
    cat norm.stderr >&2 || true
    cp "$input_vcf" "$normalized_vcf"
    normalization_mode="copy_fallback"
  fi
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[normalize] bcftools missing and fallback disabled" >&2
    exit 127
  fi
  echo "[normalize] dev fallback copy for ${sample_id}; bcftools unavailable" >&2
  cp "$input_vcf" "$normalized_vcf"
  normalization_mode="dev_fallback_copy"
fi

# Generate stats
if [[ "$have_bcftools" == "true" ]]; then
  bcftools stats "$normalized_vcf" > "$stats_file" 2>/dev/null || true
fi

# Compress and index
if [[ "$have_bgzip" == "true" ]]; then
  bgzip -c "$normalized_vcf" > "$normalized_vcf_gz"
else
  gzip -c "$normalized_vcf" > "$normalized_vcf_gz"
fi

if [[ "$have_tabix" == "true" ]]; then
  tabix -f -p vcf "$normalized_vcf_gz" 2>/dev/null || true
fi

# Count records
record_count=0
if [[ "$have_bcftools" == "true" ]]; then
  record_count=$(bcftools view -H "$normalized_vcf" 2>/dev/null | wc -l || echo "0")
fi

# Emit ingest JSON
cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "normalize",
  "payload": {
    "normalized_vcf_path": "${normalized_vcf}",
    "normalized_vcf_gz_path": "${normalized_vcf_gz}",
    "stats_file_path": "${stats_file}",
    "normalization_mode": "${normalization_mode}",
    "record_count": ${record_count},
    "source_files": ["${normalized_vcf}", "${normalized_vcf_gz}", "${stats_file}"]
  }
}
JSON

echo "[normalize] completed for ${sample_id}: mode=${normalization_mode} records=${record_count}" >&2
