#!/usr/bin/env bash
set -euo pipefail

# CNV calling stage — runs CNVkit on a sorted BAM
# Usage: run_cnv_calling_stage.sh <sample_id> <bam> <reference_fasta> <threads> <allow_dev_fallback>

sample_id="$1"
bam="$2"
reference_fasta="$3"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"

cnv_tsv="${sample_id}.cnv.segments.tsv"
ingest="${sample_id}.cnv.ingest.json"

have_cnvkit=false
if command -v cnvkit.py >/dev/null 2>&1; then
  have_cnvkit=true
fi

have_samtools=false
if command -v samtools >/dev/null 2>&1; then
  have_samtools=true
fi

bam_ready=false
if [[ -s "$bam" ]] && $have_samtools && samtools quickcheck "$bam" >/dev/null 2>&1; then
  bam_ready=true
fi

if [[ "$have_cnvkit" == "true" && "$bam_ready" == "true" ]]; then
  echo "[cnv] running CNVkit for ${sample_id}" >&2
  # For WGS use CNVkit's whole-genome mode. `--reference` expects a CNVkit
  # .cnn reference, not a FASTA; passing FASTA makes CNVkit parse `>chr20` as
  # a tabular header and fail. The FASTA belongs in `--fasta`.
  if cnvkit.py batch "$bam" \
    --normal \
    --method wgs \
    --fasta "$reference_fasta" \
    --output-dir "${sample_id}_cnvkit" \
    --processes "$threads" 2>&1 | tail -20; then
    cns_file="${sample_id}_cnvkit/$(basename "$bam" .bam).cns"
    if [[ -f "$cns_file" ]]; then
      cp "$cns_file" "$cnv_tsv"
      cnv_mode="cnvkit"
    else
      echo "[cnv] CNVkit completed but did not produce .cns; emitting empty segments" >&2
      echo -e "chromosome\tstart\tend\tgene\tlog2\tdepth\tprobes\tweight" > "$cnv_tsv"
      cnv_mode="cnvkit_empty"
    fi
  else
    echo "[cnv] CNVkit did not produce callable segments for this input; emitting empty segments" >&2
    echo -e "chromosome\tstart\tend\tgene\tlog2\tdepth\tprobes\tweight" > "$cnv_tsv"
    cnv_mode="cnvkit_unavailable"
  fi
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[cnv] missing CNVkit/valid BAM and fallback disabled" >&2
    exit 127
  fi

  echo "[cnv] dev fallback for ${sample_id}; CNVkit not available; emitting empty non-diagnostic CNV artifact" >&2
  cat > "$cnv_tsv" <<'EOF'
chromosome	start	end	gene	log2	depth	probes	weight
EOF
  cnv_mode="dev_fallback"
fi

segment_count=$(tail -n +2 "$cnv_tsv" 2>/dev/null | wc -l || echo "0")

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "cnv",
  "payload": {
    "cnv_segments_tsv_path": "${cnv_tsv}",
    "source_files": ["${cnv_tsv}"],
    "cnv_mode": "${cnv_mode}",
    "segment_count": ${segment_count}
  }
}
JSON
