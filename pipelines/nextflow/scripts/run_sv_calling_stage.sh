#!/usr/bin/env bash
set -euo pipefail

# SV calling stage — runs Manta + Delly on a sorted BAM
# Usage: run_sv_calling_stage.sh <sample_id> <bam> <reference_fasta> <threads> <allow_dev_fallback>

sample_id="$1"
bam="$2"
reference_fasta="$3"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"

sv_vcf="${sample_id}.sv.vcf"
ingest="${sample_id}.sv.ingest.json"

have_manta=false
# Manta 1.6 packaging commonly invokes python2 internally. Treat it as
# unavailable when python2 is absent, otherwise full_optional runs report a
# fake tool success and then fail at runtime with `env: python2`.
if command -v configManta.py >/dev/null 2>&1 && command -v python2 >/dev/null 2>&1; then
  have_manta=true
fi

have_delly=false
if command -v delly >/dev/null 2>&1; then
  have_delly=true
fi

have_samtools=false
if command -v samtools >/dev/null 2>&1; then
  have_samtools=true
fi

bam_ready=false
if [[ -s "$bam" ]] && $have_samtools && samtools quickcheck "$bam" >/dev/null 2>&1; then
  bam_ready=true
fi

if [[ ("$have_manta" == "true" || "$have_delly" == "true") && "$bam_ready" == "true" ]]; then
  sv_mode_parts=()

  if [[ "$have_manta" == "true" ]]; then
    echo "[sv] running Manta for ${sample_id}" >&2
    if configManta.py --bam "$bam" --referenceFasta "$reference_fasta" --runDir "${sample_id}_manta" 2>&1 | tail -10 && \
       "${sample_id}_manta/runWorkflow.py" -m local -j "$threads" 2>&1 | tail -10; then
      if [[ -f "${sample_id}_manta/results/variants/diploidSV.vcf.gz" ]]; then
        gunzip -c "${sample_id}_manta/results/variants/diploidSV.vcf.gz" > "${sample_id}.manta.vcf"
        sv_mode_parts+=("manta")
      fi
    else
      echo "[sv] Manta failed; continuing with other available SV callers" >&2
    fi
  fi

  if [[ "$have_delly" == "true" ]]; then
    echo "[sv] running Delly for ${sample_id}" >&2
    delly call -g "$reference_fasta" -o "${sample_id}.delly.bcf" "$bam" 2>&1 | tail -5
    bcftools view "${sample_id}.delly.bcf" -o "${sample_id}.delly.vcf" 2>/dev/null || true
    sv_mode_parts+=("delly")
  fi

  # Merge or pick available VCF
  if [[ -f "${sample_id}.manta.vcf" && -f "${sample_id}.delly.vcf" ]]; then
    bcftools merge --force-samples "${sample_id}.manta.vcf" "${sample_id}.delly.vcf" -o "$sv_vcf" 2>/dev/null || \
    cat "${sample_id}.manta.vcf" > "$sv_vcf"
    sv_mode="merged_$(IFS=+; echo "${sv_mode_parts[*]}")"
  elif [[ -f "${sample_id}.manta.vcf" ]]; then
    cat "${sample_id}.manta.vcf" > "$sv_vcf"
    sv_mode="manta"
  elif [[ -f "${sample_id}.delly.vcf" ]]; then
    cat "${sample_id}.delly.vcf" > "$sv_vcf"
    sv_mode="delly"
  else
    echo "[sv] no SV calls produced" >&2
    sv_mode="empty"
  fi
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[sv] missing Manta/Delly/valid BAM and fallback disabled" >&2
    exit 127
  fi

  echo "[sv] dev fallback for ${sample_id}; SV callers not available; emitting empty non-diagnostic SV artifact" >&2
  cat > "$sv_vcf" <<'VCF'
##fileformat=VCFv4.2
##source=wgs-cockpit-dev-sv-unavailable
##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Type of structural variant">
##INFO=<ID=SVLEN,Number=.,Type=Integer,Description="Difference in length between REF and ALT alleles">
##INFO=<ID=END,Number=1,Type=Integer,Description="End position of the structural variant">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##FORMAT=<ID=PR,Number=.,Type=Integer,Description="Spanning paired-read support for the ref and alt alleles">
##FORMAT=<ID=SR,Number=.,Type=Integer,Description="Split-read support for the ref and alt alleles">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	SAMPLE
VCF
  sv_mode="dev_fallback"
fi

if [[ -f "$sv_vcf" ]]; then
  sv_count=$(awk 'BEGIN{n=0} $0 !~ /^#/ {n++} END{print n}' "$sv_vcf")
else
  sv_count=0
fi

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "sv",
  "payload": {
    "sv_vcf_path": "${sv_vcf}",
    "source_files": ["${sv_vcf}"],
    "sv_mode": "${sv_mode}",
    "sv_count": ${sv_count}
  }
}
JSON
