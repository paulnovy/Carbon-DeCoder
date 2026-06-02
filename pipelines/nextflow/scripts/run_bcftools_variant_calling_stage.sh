#!/usr/bin/env bash
set -euo pipefail

sample_id="$1"
bam="$2"
reference_fasta="$3"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"

raw_vcf="${sample_id}.bcftools.raw.vcf"
raw_vcf_gz="${raw_vcf}.gz"
raw_tbi="${raw_vcf_gz}.tbi"
stats_txt="${sample_id}.bcftools.stats.txt"
ingest="${sample_id}.variants.bcftools.ingest.json"

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

bam_ready=false
if [[ -s "$bam" ]] && command -v samtools >/dev/null 2>&1 && samtools quickcheck "$bam" >/dev/null 2>&1; then
  bam_ready=true
fi

ref_ready=false
if [[ -s "$reference_fasta" ]]; then
  ref_ready=true
fi

if [[ "$have_bcftools" == "true" && "$bam_ready" == "true" && "$ref_ready" == "true" ]]; then
  echo "[variants] running bcftools mpileup/call for ${sample_id}" >&2
  bcftools mpileup --threads "$threads" -Ou -f "$reference_fasta" "$bam" \
    | bcftools call --threads "$threads" -mv -Ov -o "$raw_vcf"
  bcftools stats "$raw_vcf" > "$stats_txt"
  calling_mode="bcftools_mpileup_call"
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[variants] missing bcftools/reference/valid BAM and fallback disabled" >&2
    echo "[variants] bcftools=${have_bcftools}; reference_ready=${ref_ready}; bam_ready=${bam_ready}" >&2
    exit 127
  fi

  echo "[variants] dev fallback VCF for ${sample_id}; real caller inputs unavailable" >&2
  cat > "$raw_vcf" <<'VCF'
##fileformat=VCFv4.2
##source=wgs-cockpit-dev-bcftools-fallback
##INFO=<ID=CALLERS,Number=.,Type=String,Description="Callers that emitted this variant">
##INFO=<ID=CALLER_AGREEMENT,Number=1,Type=Float,Description="Technical caller agreement score">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	SAMPLE
chr1	100	.	A	G	60	PASS	CALLERS=bcftools;CALLER_AGREEMENT=0.55;GNOMAD_AF=0.0;CSQ=intergenic_variant	GT:GQ:DP:AD	0/1:48:24:12,12
VCF
  cat > "$stats_txt" <<'EOF'
SN	0	number of records:	1
SN	0	number of SNPs:	1
EOF
  calling_mode="dev_fallback_bcftools_vcf"
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
    "replace_existing_for_run": true,
    "source_files": ["${raw_vcf}", "${raw_vcf_gz}", "${raw_tbi}", "${stats_txt}"],
    "variant_calling_mode": "${calling_mode}",
    "caller": "bcftools"
  }
}
JSON
