#!/usr/bin/env bash
set -euo pipefail

# WGS Cockpit — Annotation Stage (VEP or bcftools csq)
# Runs VEP when explicitly enabled, otherwise bcftools csq for lightweight consequence calling.
# Usage: run_annotation_stage.sh <sample_id> <normalized_vcf> <reference_fasta> <gff_file> <threads> <allow_dev_fallback>

sample_id="$1"
input_vcf="$2"
reference_fasta="$3"
gff_file="${4:-}"
threads="${5:-4}"
allow_dev_fallback="${6:-true}"

annotated_vcf="${sample_id}.variants.annotated.vcf"
annotated_vcf_gz="${annotated_vcf}.gz"
stats_file="${annotated_vcf}.stats"
ingest="${sample_id}.annotation.ingest.json"

if [[ ! -s "$input_vcf" ]]; then
  echo "[annotation] input VCF not found or empty: ${input_vcf}" >&2
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

have_vep=false
if command -v vep >/dev/null 2>&1; then
  have_vep=true
fi

annotation_mode="unknown"
csq_field="none"

vep_enabled="${WGS_VEP_ENABLED:-false}"
vep_cache_dir="${WGS_VEP_CACHE_DIR:-}"
vep_assembly="${WGS_VEP_ASSEMBLY:-GRCh38}"
vep_extra_args="${WGS_VEP_EXTRA_ARGS:-}"

if [[ "$vep_enabled" == "true" && "$have_vep" == "true" ]]; then
  echo "[annotation] running VEP for ${sample_id}" >&2
  vep_cmd=(vep --input_file "$input_vcf" --output_file "$annotated_vcf" --vcf --force_overwrite --fork "$threads" --assembly "$vep_assembly")
  if [[ -n "$vep_cache_dir" && -d "$vep_cache_dir" ]]; then
    vep_cmd+=(--offline --cache --dir_cache "$vep_cache_dir")
  fi
  if [[ -s "$reference_fasta" ]]; then
    vep_cmd+=(--fasta "$reference_fasta")
  fi
  if [[ -n "$vep_extra_args" ]]; then
    # shellcheck disable=SC2206
    vep_extra_parts=($vep_extra_args)
    vep_cmd+=("${vep_extra_parts[@]}")
  fi
  if "${vep_cmd[@]}" 2>vep.stderr; then
    annotation_mode="vep"
    csq_field="CSQ"
  elif [[ "$allow_dev_fallback" == "true" ]]; then
    echo "[annotation] VEP failed, falling back to bcftools/passthrough" >&2
    cat vep.stderr >&2 || true
  else
    echo "[annotation] VEP failed and fallback disabled" >&2
    cat vep.stderr >&2 || true
    exit 1
  fi
fi

if [[ "$annotation_mode" == "unknown" && "$have_bcftools" == "true" ]]; then
  echo "[annotation] running bcftools csq for ${sample_id}" >&2
  csq_ok=false

  # Try bcftools csq with GFF if provided and reference available
  if [[ -n "$gff_file" && -s "$gff_file" && -s "$reference_fasta" ]]; then
    echo "[annotation] using bcftools csq with GFF: ${gff_file}" >&2
    if bcftools csq -f "$reference_fasta" -g "$gff_file" --threads "$threads" -Ov -o "$annotated_vcf" "$input_vcf" 2>csq.stderr; then
      annotation_mode="bcftools_csq_gff"
      csq_field="BCSQ"
      csq_ok=true
    else
      echo "[annotation] bcftools csq with GFF failed, trying without" >&2
      cat csq.stderr >&2 || true
    fi
  fi

  # Fallback: copy input VCF and add minimal CSQ header
  if [[ "$csq_ok" != "true" ]]; then
    if [[ "$allow_dev_fallback" == "true" ]]; then
      echo "[annotation] GFF not available or csq failed; copying input VCF as-is" >&2
      cp "$input_vcf" "$annotated_vcf"
      annotation_mode="passthrough_copy"
      csq_field="none"
      csq_ok=true
    else
      echo "[annotation] annotation failed and fallback disabled" >&2
      exit 1
    fi
  fi
elif [[ "$annotation_mode" == "unknown" ]]; then
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[annotation] VEP/bcftools missing and fallback disabled" >&2
    exit 127
  fi
  echo "[annotation] dev fallback copy for ${sample_id}; VEP/bcftools unavailable" >&2
  cp "$input_vcf" "$annotated_vcf"
  annotation_mode="dev_fallback_copy"
  csq_field="none"
fi

# Generate stats
if [[ "$have_bcftools" == "true" ]]; then
  bcftools stats "$annotated_vcf" > "$stats_file" 2>/dev/null || true
fi

# Compress and index
if [[ "$have_bgzip" == "true" ]]; then
  bgzip -c "$annotated_vcf" > "$annotated_vcf_gz"
else
  gzip -c "$annotated_vcf" > "$annotated_vcf_gz"
fi

if [[ "$have_tabix" == "true" ]]; then
  tabix -f -p vcf "$annotated_vcf_gz" 2>/dev/null || true
fi

# Count records and CSQ annotations
record_count=0
csq_count=0
if [[ "$have_bcftools" == "true" ]]; then
  record_count=$(bcftools view -H "$annotated_vcf" 2>/dev/null | wc -l || echo "0")
  if [[ "$csq_field" == "BCSQ" || "$csq_field" == "CSQ" ]]; then
    csq_count=$(bcftools view -H "$annotated_vcf" 2>/dev/null | grep -c "${csq_field}=" || echo "0")
  fi
fi

# Emit ingest JSON
cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "annotation",
  "payload": {
    "annotated_vcf_path": "${annotated_vcf}",
    "annotated_vcf_gz_path": "${annotated_vcf_gz}",
    "stats_file_path": "${stats_file}",
    "annotation_mode": "${annotation_mode}",
    "csq_field": "${csq_field}",
    "record_count": ${record_count},
    "csq_annotated_count": ${csq_count},
    "source_files": ["${annotated_vcf}", "${annotated_vcf_gz}", "${stats_file}"]
  }
}
JSON

echo "[annotation] completed for ${sample_id}: mode=${annotation_mode} records=${record_count} csq=${csq_count}" >&2
