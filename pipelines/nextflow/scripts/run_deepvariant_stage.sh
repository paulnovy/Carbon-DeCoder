#!/usr/bin/env bash
set -euo pipefail

sample_id="$1"
bam="$2"
reference_fasta="$3"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"
model_type="${6:-WGS}"

raw_vcf="${sample_id}.deepvariant.raw.vcf"
raw_vcf_gz="${raw_vcf}.gz"
raw_tbi="${raw_vcf_gz}.tbi"
gvcf="${sample_id}.deepvariant.g.vcf"
stats_txt="${sample_id}.deepvariant.stats.txt"
ingest="${sample_id}.variants.deepvariant.ingest.json"

have_dv=false
if command -v run_deepvariant >/dev/null 2>&1; then
  have_dv=true
elif command -v /opt/deepvariant/bin/run_deepvariant >/dev/null 2>&1; then
  have_dv=true
  DV_BIN="/opt/deepvariant/bin/run_deepvariant"
fi

DV_BIN="${DV_BIN:-run_deepvariant}"

have_bgzip=false
if command -v bgzip >/dev/null 2>&1; then
  have_bgzip=true
fi

have_tabix=false
if command -v tabix >/dev/null 2>&1; then
  have_tabix=true
fi

bam_ready=false
if [[ -s "$bam" ]] && command -v samtools >/dev/null 2>&1 && samtools quickcheck "$bam" >/dev/null 2>&1; then
  bam_ready=true
fi

ref_ready=false
if [[ -s "$reference_fasta" ]]; then
  ref_ready=true
fi

if [[ "$have_dv" == "true" && "$bam_ready" == "true" && "$ref_ready" == "true" ]]; then
  echo "[variants] running DeepVariant (${model_type}) for ${sample_id}" >&2
  "$DV_BIN" \
    --model_type="${model_type}" \
    --ref="$reference_fasta" \
    --reads="$bam" \
    --output_vcf="$raw_vcf" \
    --output_gvcf="$gvcf" \
    --num_shards="$threads" \
    --intermediate_results_dir="${sample_id}_dv_tmp" 2>&1 | tail -30

  # Cleanup temp dir
  rm -rf "${sample_id}_dv_tmp"

  # Compute stats
  if command -v bcftools >/dev/null 2>&1; then
    bcftools stats "$raw_vcf" > "$stats_txt"
  else
    n_records=$(grep -cv "^#" "$raw_vcf" || echo "0")
    cat > "$stats_txt" <<EOF
SN	0	number of records:	${n_records}
EOF
  fi
  calling_mode="deepvariant_${model_type,,}"
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[variants] missing DeepVariant/reference/valid BAM and fallback disabled" >&2
    echo "[variants] deepvariant=${have_dv}; reference_ready=${ref_ready}; bam_ready=${bam_ready}" >&2
    exit 127
  fi

  echo "[variants] dev fallback VCF for ${sample_id}; DeepVariant unavailable" >&2
  cat > "$raw_vcf" <<'VCF'
##fileformat=VCFv4.2
##source=wgs-cockpit-dev-deepvariant-fallback
##INFO=<ID=CALLERS,Number=.,Type=String,Description="Callers that emitted this variant">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	SAMPLE
chr20	100	.	A	G	60	PASS	CALLERS=DeepVariant;CALLER_AGREEMENT=0.55	GT:GQ:DP:AD	0/1:48:24:12,12
VCF
  cat > "$stats_txt" <<'EOF'
SN	0	number of records:	1
SN	0	number of SNPs:	1
EOF
  calling_mode="dev_fallback_deepvariant_vcf"
fi

if [[ "$have_bgzip" == "true" ]]; then
  bgzip -c "$raw_vcf" > "$raw_vcf_gz"
else
  gzip -c "$raw_vcf" > "$raw_vcf_gz"
fi

if [[ "$have_tabix" == "true" ]]; then
  tabix -f -p vcf "$raw_vcf_gz" || printf 'tabix_index_failed\n' > "$raw_tbi"
else
  printf 'tabix_unavailable\n' > "$raw_tbi"
fi

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "variants",
  "payload": {
    "variants_vcf_path": "${raw_vcf}",
    "replace_existing_for_run": false,
    "source_files": ["${raw_vcf}", "${raw_vcf_gz}", "${raw_tbi}", "${stats_txt}"],
    "variant_calling_mode": "${calling_mode}",
    "caller": "DeepVariant"
  }
}
JSON
