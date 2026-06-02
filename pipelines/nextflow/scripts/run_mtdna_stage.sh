#!/usr/bin/env bash
set -euo pipefail

# mtDNA analysis stage — extracts and calls variants from mitochondrial DNA
# Usage: run_mtdna_stage.sh <sample_id> <bam> <reference_fasta> <threads> <allow_dev_fallback>

sample_id="$1"
bam="$2"
reference_fasta="$3"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"

mtdna_vcf="${sample_id}.mtdna.vcf"
mtdna_report="${sample_id}.mtdna.report.json"
ingest="${sample_id}.mtdna.ingest.json"

have_gatk=false
if command -v gatk >/dev/null 2>&1; then
  have_gatk=true
fi

have_samtools=false
if command -v samtools >/dev/null 2>&1; then
  have_samtools=true
fi

select_mtdna_contig() {
  local bam_path="$1"
  local ref_fasta="$2"
  if $have_samtools; then
    samtools idxstats "$bam_path" 2>/dev/null | awk '
      BEGIN {
        split("chrM MT M chrMT rCRS RSRS", order, " ")
        for (i in order) wanted[order[i]] = i
      }
      $1 in wanted { print $1; exit }
    ' || true
  fi
  if [[ -s "${ref_fasta}.fai" ]]; then
    awk '
      BEGIN {
        split("chrM MT M chrMT rCRS RSRS", order, " ")
        for (i in order) wanted[order[i]] = i
      }
      $1 in wanted { print $1; exit }
    ' "${ref_fasta}.fai" || true
  fi
}

bam_ready=false
if [[ -s "$bam" ]] && $have_samtools && samtools quickcheck "$bam" >/dev/null 2>&1; then
  bam_ready=true
fi

if [[ "$have_gatk" == "true" && "$bam_ready" == "true" ]]; then
  echo "[mtdna] extracting mtDNA reads for ${sample_id}" >&2
  mt_bam="${sample_id}.mt.bam"
  mtdna_contig="$(select_mtdna_contig "$bam" "$reference_fasta" | head -n 1)"
  if [[ -n "$mtdna_contig" ]]; then
    echo "[mtdna] selected mitochondrial contig: ${mtdna_contig}" >&2
    samtools view -b "$bam" "$mtdna_contig" > "$mt_bam" 2>/dev/null || true
    samtools index "$mt_bam" 2>/dev/null || true

    echo "[mtdna] calling mtDNA variants with Mutect2 for ${sample_id}" >&2
    gatk --java-options "-Xmx2g" Mutect2 \
      -R "$reference_fasta" \
      -I "$mt_bam" \
      -mitochondria-mode \
      -O "$mtdna_vcf" 2>&1 | tail -10

    # Count variants without producing invalid JSON when the VCF has zero records.
    if [[ -f "$mtdna_vcf" ]]; then
      variant_count=$(awk 'BEGIN{n=0} $0 !~ /^#/ {n++} END{print n}' "$mtdna_vcf")
    else
      variant_count=0
    fi
    mtdna_mode="mutect2_mitochondria"
    mtdna_status="called"
    mtdna_numts_warning="false"
    mtdna_warning="mtDNA variants called with Mutect2; haplogroup requires HaploGrep downstream"
  else
    echo "[mtdna] no mitochondrial contig found in BAM idxstats/reference index" >&2
    : > "$mt_bam"
    cat > "$mtdna_vcf" <<'VCF'
##fileformat=VCFv4.2
##source=wgs-cockpit-mtdna-contig-unavailable
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	SAMPLE
VCF
    variant_count=0
    mtdna_mode="mt_contig_unavailable"
    mtdna_status="not_available"
    mtdna_numts_warning="true"
    mtdna_warning="No mitochondrial contig found in BAM idxstats/reference index; no synthetic mtDNA calls emitted"
  fi
else
  mtdna_contig="unknown"
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[mtdna] missing GATK/valid BAM and fallback disabled" >&2
    echo "[mtdna] gatk=${have_gatk}; bam_ready=${bam_ready}" >&2
    exit 127
  fi

  echo "[mtdna] dev fallback for ${sample_id}; GATK not available; emitting empty non-diagnostic mtDNA artifact" >&2
  cat > "$mtdna_vcf" <<'VCF'
##fileformat=VCFv4.2
##source=wgs-cockpit-dev-mtdna-unavailable
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	SAMPLE
VCF
  variant_count=0
  mtdna_mode="dev_fallback"
  mtdna_status="not_available"
  mtdna_numts_warning="true"
  mtdna_warning="mtDNA calling unavailable; no synthetic haplogroup or variants emitted"
fi

cat > "$mtdna_report" <<JSON
num_variants=${variant_count}
numts_warning=${mtdna_numts_warning}
mitochondrial_contig=${mtdna_contig:-unknown}
trust_score=0
coverage_mean=0
status=${mtdna_status}
warning=${mtdna_warning}
JSON

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "mtdna",
  "payload": {
    "mtdna_vcf_path": "${mtdna_vcf}",
    "mtdna_report_path": "${mtdna_report}",
    "source_files": ["${mtdna_vcf}", "${mtdna_report}"],
    "mtdna_mode": "${mtdna_mode}"
  }
}
JSON
