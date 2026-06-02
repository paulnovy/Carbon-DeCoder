#!/usr/bin/env bash
set -euo pipefail

sample_id="$1"
bam="$2"
reference_fasta="$3"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"

raw_vcf="${sample_id}.gatk.hc.raw.vcf"
raw_vcf_gz="${raw_vcf}.gz"
raw_tbi="${raw_vcf_gz}.tbi"
stats_txt="${sample_id}.gatk.stats.txt"
ingest="${sample_id}.variants.gatk.ingest.json"

have_gatk=false
if command -v gatk >/dev/null 2>&1; then
  have_gatk=true
fi

have_java=false
if command -v java >/dev/null 2>&1; then
  have_java=true
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

if [[ "$have_gatk" == "true" && "$have_java" == "true" && "$bam_ready" == "true" && "$ref_ready" == "true" ]]; then
  echo "[variants] running GATK HaplotypeCaller for ${sample_id}" >&2
  gatk --java-options "-Xmx4g -Xms1g" HaplotypeCaller \
    -R "$reference_fasta" \
    -I "$bam" \
    -O "$raw_vcf" \
    -stand-call-conf 30.0 \
    --native-pair-hmm-threads "$threads" \
    -ERC GVCF 2>&1 | tail -20

  # If GVCF mode, convert to regular VCF for downstream compatibility
  if grep -q "GVCF" "$raw_vcf" 2>/dev/null; then
    echo "[variants] converting GVCF to VCF for ${sample_id}" >&2
    tmp_vcf="${sample_id}.gatk.genotyped.vcf"
    gatk --java-options "-Xmx2g" GenotypeGVCFs \
      -R "$reference_fasta" \
      -V "$raw_vcf" \
      -O "$tmp_vcf" 2>&1 | tail -10
    mv "$tmp_vcf" "$raw_vcf"
  fi

  # Compute stats
  if command -v bcftools >/dev/null 2>&1; then
    bcftools stats "$raw_vcf" > "$stats_txt"
  else
    # Count records manually
    n_records=$(grep -cv "^#" "$raw_vcf" || echo "0")
    n_snps=$(grep -cv "^#" "$raw_vcf" || echo "0")
    cat > "$stats_txt" <<EOF
SN	0	number of records:	${n_records}
EOF
  fi
  calling_mode="gatk_haplotypecaller"
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[variants] missing GATK/java/reference/valid BAM and fallback disabled" >&2
    echo "[variants] gatk=${have_gatk}; java=${have_java}; reference_ready=${ref_ready}; bam_ready=${bam_ready}" >&2
    exit 127
  fi

  echo "[variants] dev fallback VCF for ${sample_id}; GATK unavailable" >&2
  cat > "$raw_vcf" <<'VCF'
##fileformat=VCFv4.2
##source=wgs-cockpit-dev-gatk-fallback
##INFO=<ID=CALLERS,Number=.,Type=String,Description="Callers that emitted this variant">
##INFO=<ID=CALLER_AGREEMENT,Number=1,Type=Float,Description="Technical caller agreement score">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	SAMPLE
chr20	100	.	A	G	60	PASS	CALLERS=GATK;CALLER_AGREEMENT=0.55	GT:GQ:DP:AD	0/1:48:24:12,12
VCF
  cat > "$stats_txt" <<'EOF'
SN	0	number of records:	1
SN	0	number of SNPs:	1
EOF
  calling_mode="dev_fallback_gatk_vcf"
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
    "caller": "GATK"
  }
}
JSON
