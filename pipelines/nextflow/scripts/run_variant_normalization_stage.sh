#!/usr/bin/env bash
set -euo pipefail

sample_id="$1"
input_vcf="$2"
reference_fasta="$3"
allow_dev_fallback="${4:-true}"

normalized_vcf="${sample_id}.variants.normalized.vcf"
normalized_vcf_gz="${normalized_vcf}.gz"
normalized_tbi="${normalized_vcf_gz}.tbi"
ingest="${sample_id}.variants.ingest.json"

if [[ ! -s "$input_vcf" ]]; then
  echo "[variants] input VCF not found or empty: ${input_vcf}" >&2
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

if [[ "$have_bcftools" == "true" ]]; then
  echo "[variants] running bcftools normalization for ${sample_id}" >&2
  norm_ok=false
  if [[ -s "$reference_fasta" ]]; then
    if bcftools norm -m -any -f "$reference_fasta" "$input_vcf" -Ov -o "$normalized_vcf" 2>/dev/null; then
      normalization_mode="bcftools_norm_ref"
      norm_ok=true
    fi
  fi
  if [[ "$norm_ok" != "true" ]]; then
    if bcftools norm -m -any "$input_vcf" -Ov -o "$normalized_vcf" 2>/dev/null; then
      normalization_mode="bcftools_norm_split_only"
      norm_ok=true
    fi
  fi
  if [[ "$norm_ok" != "true" ]]; then
    echo "[variants] bcftools norm failed, falling back to copy" >&2
    cp "$input_vcf" "$normalized_vcf"
    normalization_mode="bcftools_norm_copy_fallback"
  fi
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[variants] bcftools missing and fallback disabled" >&2
    exit 127
  fi
  echo "[variants] dev fallback copy for ${sample_id}; bcftools unavailable" >&2
  cp "$input_vcf" "$normalized_vcf"
  normalization_mode="dev_fallback_copy"
fi

if [[ "$have_bgzip" == "true" ]]; then
  bgzip -c "$normalized_vcf" > "$normalized_vcf_gz"
else
  gzip -c "$normalized_vcf" > "$normalized_vcf_gz"
fi

if [[ "$have_tabix" == "true" ]]; then
  tabix -f -p vcf "$normalized_vcf_gz" || printf 'tabix_index_failed\n' > "$normalized_tbi"
else
  printf 'tabix_unavailable\n' > "$normalized_tbi"
fi

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "variants",
  "payload": {
    "variants_vcf_path": "${normalized_vcf}",
    "replace_existing_for_run": true,
    "source_files": ["${normalized_vcf}", "${normalized_vcf_gz}", "${normalized_tbi}"],
    "normalization_mode": "${normalization_mode}"
  }
}
JSON
